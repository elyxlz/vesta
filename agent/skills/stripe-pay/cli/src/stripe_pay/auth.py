"""OAuth authorize flow against Stripe Link Wallet for Agents.

Flow:
  1. We open a short-lived localhost HTTP server to capture the redirect.
  2. We open the user's browser to Stripe's Link OAuth consent URL.
  3. The user signs in / approves on Stripe, Stripe redirects to localhost
     with ``?code=...``.
  4. We exchange the code for an access + refresh token via Stripe's token
     endpoint, using the user's restricted API key as the basic-auth password.
  5. The token bundle is written to ``~/.stripe-pay/credentials.json`` (mode
     0600). Re-running the command refreshes the token.

The skill never stores raw card data — only OAuth tokens.
"""

from __future__ import annotations

import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from .config import (
    LINK_OAUTH_AUTHORIZE_URL,
    LINK_OAUTH_SCOPE,
    LINK_OAUTH_TOKEN_URL,
    Config,
)


class AuthError(RuntimeError):
    """Raised when the OAuth flow can't complete."""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def authorize(config: Config, *, open_browser: bool = True) -> dict:
    """Run the full OAuth authorize flow. Returns a status dict.

    Idempotent — re-running refreshes the token cleanly.
    """
    api_key = config.load_api_key()
    if not api_key:
        raise AuthError(f"no API key found. Write your restricted Stripe key to {config.api_key_file} (chmod 600) — see SETUP.md step 2.")

    state = secrets.token_urlsafe(24)
    server, port = _start_callback_server(state)
    redirect_uri = f"http://127.0.0.1:{port}/callback"

    auth_url = _build_authorize_url(api_key, redirect_uri, state)

    print(f"Opening browser to: {auth_url}", file=sys.stderr)
    if open_browser:
        try:
            webbrowser.open(auth_url)
        except webbrowser.Error:
            print("(could not auto-open; visit the URL manually)", file=sys.stderr)

    # Wait up to 5 minutes for the redirect.
    deadline = time.time() + 300
    while server.captured_code is None and server.captured_error is None:
        if time.time() > deadline:
            server.shutdown()
            raise AuthError("timed out waiting for OAuth callback")
        time.sleep(0.25)
    server.shutdown()

    if server.captured_error:
        raise AuthError(f"OAuth error from Stripe: {server.captured_error}")

    code = server.captured_code
    assert code is not None  # for the type-checker

    token_payload = _exchange_code_for_token(code, redirect_uri, api_key)
    config.save_credentials(
        {
            "obtained_at": int(time.time()),
            "redirect_uri": redirect_uri,
            "scope": token_payload.get("scope", LINK_OAUTH_SCOPE),
            **token_payload,
        }
    )

    return {
        "status": "authorized",
        "credentials_path": str(config.credentials_file),
        "scope": token_payload.get("scope", LINK_OAUTH_SCOPE),
    }


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


def _build_authorize_url(api_key: str, redirect_uri: str, state: str) -> str:
    """Build the Stripe Link OAuth consent URL."""
    # The client_id Stripe expects for the agent OAuth flow is derived from
    # the restricted key's account; per the Agent Toolkit docs you can pass
    # the key prefix as ``client_id``. If a future Stripe build requires a
    # separately-registered ``ca_*`` client id, override via env var.
    import os

    client_id = os.environ.get("STRIPE_PAY_CLIENT_ID", api_key)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": LINK_OAUTH_SCOPE,
        "state": state,
    }
    return f"{LINK_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


# ---------------------------------------------------------------------------
# Localhost HTTP callback server
# ---------------------------------------------------------------------------


class _CallbackServer(HTTPServer):
    """HTTP server that captures the OAuth redirect.

    Stores the captured ``code`` (or ``error``) on the server instance so the
    caller can poll ``server.captured_code`` after starting it.
    """

    captured_code: str | None = None
    captured_error: str | None = None
    expected_state: str | None = None


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _CallbackServer  # type: ignore[assignment]

    def do_GET(self) -> None:  # noqa: N802 — http.server's required name
        url = urlparse(self.path)
        params = parse_qs(url.query)
        state = params.get("state", [None])[0]
        if state != self.server.expected_state:
            self._reply(400, "state mismatch — possible CSRF, aborting")
            self.server.captured_error = "state_mismatch"
            return

        if "error" in params:
            err = params.get("error_description", params["error"])[0]
            self._reply(400, f"error: {err}")
            self.server.captured_error = err
            return

        code = params.get("code", [None])[0]
        if not code:
            self._reply(400, "no code in callback")
            self.server.captured_error = "no_code"
            return

        self.server.captured_code = code
        self._reply(
            200,
            "<h2>Authorized.</h2><p>You can close this tab and return to your terminal.</p>",
        )

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, N802
        # Silence the default access-log spam.
        return

    def _reply(self, status: int, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def _start_callback_server(state: str) -> tuple[_CallbackServer, int]:
    """Start the callback server on a free port. Returns (server, port).

    Tries a fixed default port first, then asks the OS for a free one.
    """
    from .config import DEFAULT_CALLBACK_PORT

    for port in (DEFAULT_CALLBACK_PORT, 0):
        try:
            server = _CallbackServer(("127.0.0.1", port), _CallbackHandler)
        except OSError:
            continue
        server.expected_state = state
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, server.server_address[1]
    raise AuthError("could not bind any localhost port for the OAuth callback")


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def _exchange_code_for_token(code: str, redirect_uri: str, api_key: str) -> dict:
    """Exchange the auth code for an access + refresh token."""
    resp = requests.post(
        LINK_OAUTH_TOKEN_URL,
        auth=(api_key, ""),
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        raise AuthError(f"token exchange failed: HTTP {resp.status_code}: {resp.text[:300]}")
    payload = resp.json()
    if "access_token" not in payload:
        raise AuthError(f"token exchange returned no access_token: {payload}")
    return payload


# ---------------------------------------------------------------------------
# Refresh / load
# ---------------------------------------------------------------------------


def load_active_token(config: Config) -> str:
    """Return a currently-valid access token, refreshing if needed.

    Raises ``AuthError`` if no credentials are saved.
    """
    creds = config.load_credentials()
    if not creds:
        raise AuthError("no credentials. Run `stripe-pay authorize` first (see SETUP.md).")
    expires_at = int(creds.get("obtained_at", 0)) + int(creds.get("expires_in", 0))
    # Refresh 60s before expiry to avoid edge cases.
    if expires_at and time.time() >= expires_at - 60:
        creds = _refresh(config, creds)
    token = creds.get("access_token")
    if not token:
        raise AuthError("credentials.json missing access_token")
    return token


def _refresh(config: Config, creds: dict) -> dict:
    """Refresh the access token using the saved refresh token."""
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        raise AuthError("saved credentials have no refresh_token — re-run `stripe-pay authorize`")
    api_key = config.load_api_key()
    if not api_key:
        raise AuthError("no API key on disk; re-run setup")
    resp = requests.post(
        LINK_OAUTH_TOKEN_URL,
        auth=(api_key, ""),
        data={"grant_type": "refresh_token", "refresh_token": refresh_token},
        timeout=30,
    )
    if resp.status_code != 200:
        raise AuthError(f"token refresh failed: HTTP {resp.status_code}: {resp.text[:300]}")
    payload = resp.json()
    new_creds = {
        **creds,
        **payload,
        "obtained_at": int(time.time()),
    }
    config.save_credentials(new_creds)
    return new_creds


def status(config: Config) -> dict:
    """Lightweight status check for the agent / setup script."""
    creds = config.load_credentials()
    if not creds:
        return {"status": "not_authorized"}
    obtained = creds.get("obtained_at", 0)
    expires_in = creds.get("expires_in", 0)
    expires_at = obtained + expires_in if obtained and expires_in else None
    return {
        "status": "authorized",
        "scope": creds.get("scope"),
        "expires_at": expires_at,
        "expired": expires_at is not None and time.time() >= expires_at,
    }
