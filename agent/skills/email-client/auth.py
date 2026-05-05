#!/usr/bin/env python3
"""Unified auth CLI for the imap-mail skill.

Picks a flow based on the resolved provider:

    device-flow      Microsoft personal accounts. Prints a URL + code,
                     polls until the user signs in on another device.
    loopback-oauth   Gmail. Spins up a localhost listener, opens (or
                     prints) the consent URL, captures the redirect,
                     exchanges the code for tokens.
    app-password     Yahoo / iCloud / Fastmail / generic IMAP. Prompts
                     for the app password and stores it.

Run as:
    uv run python3 auth.py                 # auto-detect from email
    uv run python3 auth.py --provider gmail
    uv run python3 auth.py --reauth        # force a fresh login

Token file ``$IMAP_MAIL_DIR/token.json`` always carries a ``provider``
key so the daemon and CLI know which strategy to use afterwards.
"""
from __future__ import annotations

import argparse
import getpass
import http.server
import json
import os
import pathlib
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import _env, _state_dir, save_token  # noqa: E402
from providers import apply_env_overrides, get_profile, resolve_provider  # noqa: E402


# -- device flow (Microsoft) ----------------------------------------


def auth_device_flow(provider: str, profile: dict) -> dict:
    import msal

    app = msal.PublicClientApplication(
        profile["oauth_client_id"], authority=profile["oauth_authority"]
    )
    flow = app.initiate_device_flow(scopes=profile["oauth_scopes"])
    if "user_code" not in flow:
        sys.exit(f"device flow init failed: {flow}")
    print(f"\nVisit:  {flow['verification_uri']}")
    print(f"Code:   {flow['user_code']}\n")
    print("Polling for completion (sign in, approve, then come back here)...")
    res = app.acquire_token_by_device_flow(flow)
    if "access_token" not in res:
        sys.exit(f"auth failed: {res}")
    res["_expires_at"] = time.time() + res.get("expires_in", 3600)
    res["provider"] = provider
    res["user"] = _env("IMAP_MAIL_USER")
    return res


# -- loopback OAuth (Google) ----------------------------------------


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    """Capture ``?code=...&state=...`` from the OAuth redirect."""

    captured: dict | None = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        type(self).captured = {
            "code": params.get("code", [None])[0],
            "state": params.get("state", [None])[0],
            "error": params.get("error", [None])[0],
        }
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        body = (
            "imap-mail: auth complete, you can close this tab.\n"
            if not type(self).captured["error"]
            else f"imap-mail: auth error: {type(self).captured['error']}\n"
        )
        self.wfile.write(body.encode())

    def log_message(self, *a, **kw):  # silence default access log
        return


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def auth_loopback_oauth(provider: str, profile: dict) -> dict:
    port = _free_port()
    redirect_uri = f"http://127.0.0.1:{port}/"
    state = secrets.token_urlsafe(16)

    auth_params = {
        "client_id": profile["oauth_client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(profile["oauth_scopes"]),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    user_hint = _env("IMAP_MAIL_USER")
    if user_hint:
        auth_params["login_hint"] = user_hint
    auth_url = profile["oauth_auth_url"] + "?" + urllib.parse.urlencode(auth_params)

    server = http.server.HTTPServer(("127.0.0.1", port), _RedirectHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    print("\nOpen this URL in a browser on any device that can reach this host:\n")
    print(f"  {auth_url}\n")
    print(f"Listening on {redirect_uri} for the redirect (Ctrl-C to cancel)...")

    try:
        # Spin until the handler captures something or the user
        # interrupts. 10 minute hard cap so a forgotten flow doesn't
        # hang forever.
        deadline = time.time() + 600
        while _RedirectHandler.captured is None and time.time() < deadline:
            time.sleep(0.2)
    finally:
        server.shutdown()

    cap = _RedirectHandler.captured
    if not cap:
        sys.exit("timed out waiting for OAuth redirect")
    if cap.get("error"):
        sys.exit(f"OAuth error: {cap['error']}")
    if cap.get("state") != state:
        sys.exit("state mismatch; aborting (possible CSRF)")
    code = cap.get("code")
    if not code:
        sys.exit("no code in redirect; aborting")

    data = urllib.parse.urlencode(
        {
            "client_id": profile["oauth_client_id"],
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = urllib.request.Request(
        profile["oauth_token_url"],
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.loads(r.read().decode())
    if "access_token" not in res:
        sys.exit(f"token exchange failed: {res}")
    res["_expires_at"] = time.time() + res.get("expires_in", 3600)
    res["provider"] = provider
    res["user"] = user_hint
    return res


# -- app password ---------------------------------------------------


def auth_app_password(provider: str, profile: dict) -> dict:
    user = _env("IMAP_MAIL_USER", required=True)
    print(f"\nProvider: {profile['label']}")
    print(f"Account:  {user}")
    print(
        "\nGenerate an app password in your provider's account settings "
        "(Yahoo, iCloud, Fastmail all have this under 'app-specific "
        "passwords' or 'security'), then paste it below.\n"
    )
    pw = os.environ.get("IMAP_MAIL_APP_PASSWORD") or getpass.getpass("App password: ")
    pw = pw.strip()
    if not pw:
        sys.exit("empty app password; aborting")
    return {
        "provider": provider,
        "user": user,
        "app_password": pw,
        "_expires_at": 0,
    }


# -- entrypoint -----------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--provider",
        default=None,
        help="provider key (e.g. gmail, microsoft-personal). "
        "Defaults to auto-detect from email or IMAP_MAIL_PROVIDER.",
    )
    ap.add_argument(
        "--reauth",
        action="store_true",
        help="force a fresh login even if a token already exists.",
    )
    args = ap.parse_args()

    env = dict(os.environ)
    if args.provider:
        env["IMAP_MAIL_PROVIDER"] = args.provider
    name, profile = resolve_provider(env)
    # When the user explicitly named a provider, drop env overrides
    # that might mismatch (host/port from a previous provider) by
    # rebuilding from the named profile.
    if args.provider:
        profile = apply_env_overrides(get_profile(args.provider), env)

    state_dir = _state_dir()
    token_path = state_dir / "token.json"
    if token_path.exists() and not args.reauth:
        existing = json.loads(token_path.read_text())
        if existing.get("provider") == name and not args.reauth:
            print(
                f"Token already exists for provider {name} at {token_path}. "
                "Pass --reauth to replace it."
            )
            return

    print(f"Authenticating as {profile['label']} ({name})...")
    strategy = profile["auth_strategy"]
    if strategy == "device-flow":
        tok = auth_device_flow(name, profile)
    elif strategy == "loopback-oauth":
        tok = auth_loopback_oauth(name, profile)
    elif strategy == "app-password":
        tok = auth_app_password(name, profile)
    else:
        sys.exit(f"unknown auth strategy {strategy!r}")

    save_token(tok)
    print(f"\nOK. Credential written to {token_path} (mode 600).")
    if strategy != "app-password":
        print(
            "Refresh tokens are long-lived; the CLI auto-refreshes "
            "the access token transparently."
        )


if __name__ == "__main__":
    main()
