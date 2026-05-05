#!/usr/bin/env python3
"""Unified auth CLI for the email-client skill.

Picks a flow based on the resolved provider:

    device-flow      Microsoft personal accounts. Prints a URL + code,
                     polls until the user signs in on another device.
    loopback-oauth   Gmail. Spins up a localhost listener, opens (or
                     prints) the consent URL, captures the redirect,
                     exchanges the code for tokens.
    app-password     Yahoo / iCloud / Fastmail / generic IMAP. Prompts
                     for the app password and stores it.

Multi-account: every credential lives at
``$EMAIL_CLIENT_DIR/accounts/<name>/token.json`` so the user can have
N accounts side by side. The active account is named via ``--account``.

Run as:
    uv run python3 auth.py --account <name>
    uv run python3 auth.py --account <name> --provider gmail
    uv run python3 auth.py --account <name> --reauth    # force a fresh login
"""
from __future__ import annotations

import argparse
import getpass
import http.server
import json
import os
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import (  # noqa: E402
    _env,
    _token_path,
    account_dir,
    list_accounts,
    load_accounts_index,
    save_accounts_index,
    save_config,
    save_token,
)
from providers import (  # noqa: E402
    apply_env_overrides,
    detect_provider,
    get_profile,
    resolve_provider,
)


# -- device flow (Microsoft) ----------------------------------------


def auth_device_flow(provider: str, profile: dict, user: str) -> dict:
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
    res["user"] = user
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
            "email-client: auth complete, you can close this tab.\n"
            if not type(self).captured["error"]
            else f"email-client: auth error: {type(self).captured['error']}\n"
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


def auth_loopback_oauth(provider: str, profile: dict, user: str) -> dict:
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
    if user:
        auth_params["login_hint"] = user
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
    res["user"] = user
    return res


# -- app password ---------------------------------------------------


def auth_app_password(provider: str, profile: dict, user: str) -> dict:
    print(f"\nProvider: {profile['label']}")
    print(f"Account:  {user}")
    print(
        "\nGenerate an app password in your provider's account settings "
        "(Yahoo, iCloud, Fastmail all have this under 'app-specific "
        "passwords' or 'security'), then paste it below.\n"
    )
    pw = (
        os.environ.get("EMAIL_CLIENT_APP_PASSWORD")
        or os.environ.get("IMAP_MAIL_APP_PASSWORD")
        or getpass.getpass("App password: ")
    )
    pw = pw.strip()
    if not pw:
        sys.exit("empty app password; aborting")
    return {
        "provider": provider,
        "user": user,
        "app_password": pw,
        "_expires_at": 0,
    }


def _resolve_user(provider: str | None, user: str | None) -> str:
    if user:
        return user
    env_user = _env("EMAIL_CLIENT_USER")
    if env_user:
        return env_user
    while True:
        entered = input("Email address: ").strip()
        if entered:
            return entered
        print("(empty; try again)")


def _resolve_named_provider(name: str | None, user: str) -> tuple[str, dict]:
    """Resolve a provider profile from an explicit name or auto-detect from the user."""
    env = dict(os.environ)
    if name:
        return name, apply_env_overrides(get_profile(name), env)
    detected = detect_provider(user) or ""
    if detected:
        return detected, apply_env_overrides(get_profile(detected), env)
    # Fall back to env-var resolution, which picks microsoft-personal as last resort.
    return resolve_provider(env)


def run_add(
    account: str,
    user: str | None = None,
    provider: str | None = None,
    reauth: bool = False,
) -> None:
    """Register or refresh an account.

    Writes ``accounts/<account>/{config.json,token.json}`` and updates
    the top-level ``accounts.json`` index.
    """
    account_dir(account)
    user = _resolve_user(provider, user)
    name, profile = _resolve_named_provider(provider, user)

    token_path = _token_path(account)
    if token_path.exists() and not reauth:
        try:
            existing = json.loads(token_path.read_text())
        except Exception:
            existing = {}
        if existing.get("provider") == name:
            print(
                f"Token already exists for account {account!r} (provider {name}) "
                f"at {token_path}. Pass --reauth to replace it."
            )
            return

    print(f"Authenticating {account!r} as {profile['label']} ({name})...")
    strategy = profile["auth_strategy"]
    if strategy == "device-flow":
        tok = auth_device_flow(name, profile, user)
    elif strategy == "loopback-oauth":
        tok = auth_loopback_oauth(name, profile, user)
    elif strategy == "app-password":
        tok = auth_app_password(name, profile, user)
    else:
        sys.exit(f"unknown auth strategy {strategy!r}")

    save_token(account, tok)

    cfg = {"user": user, "provider": name}
    save_config(account, cfg)

    idx = load_accounts_index()
    accs = list(idx.get("accounts") or [])
    if account not in accs:
        accs.append(account)
    idx["accounts"] = accs
    if not idx.get("default"):
        idx["default"] = account
    save_accounts_index(idx)

    print(f"\nOK. Credential written to {token_path} (mode 600).")
    print(f"Account {account!r} registered (default={idx['default']}).")
    if strategy != "app-password":
        print(
            "Refresh tokens are long-lived; the CLI auto-refreshes "
            "the access token transparently."
        )


def main() -> None:
    ap = argparse.ArgumentParser(prog="email-client-auth")
    ap.add_argument(
        "--account",
        default=None,
        help="account name (e.g. 'personal', 'work'). Defaults to "
        "the existing default account, or 'default' if none.",
    )
    ap.add_argument(
        "--user",
        default=None,
        help="email address. Defaults to EMAIL_CLIENT_USER, then prompts.",
    )
    ap.add_argument(
        "--provider",
        default=None,
        help="provider key (e.g. gmail, microsoft-personal). "
        "Defaults to auto-detect from email.",
    )
    ap.add_argument(
        "--reauth",
        action="store_true",
        help="force a fresh login even if a token already exists.",
    )
    args = ap.parse_args()

    account = args.account
    if not account:
        idx = load_accounts_index()
        account = idx.get("default") or (
            list_accounts()[0] if list_accounts() else "default"
        )
        print(f"(no --account given; using {account!r})", file=sys.stderr)

    run_add(
        account=account,
        user=args.user,
        provider=args.provider,
        reauth=args.reauth,
    )


if __name__ == "__main__":
    main()
