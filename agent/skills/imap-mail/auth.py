#!/usr/bin/env python3
"""Device-flow OAuth2 login. Runs once at setup time.

Prints a URL + code; user signs in; this script polls until the user
completes the flow, then writes the access + refresh token to
$IMAP_MAIL_DIR/token.json (default ~/.imap-mail/token.json).
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

import msal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import (  # noqa: E402
    DEFAULT_AUTHORITY,
    DEFAULT_SCOPES,
    THUNDERBIRD_CLIENT_ID,
    _env,
    _state_dir,
)


def main() -> None:
    client_id = _env("IMAP_MAIL_OAUTH_CLIENT_ID", THUNDERBIRD_CLIENT_ID)
    authority = _env("IMAP_MAIL_OAUTH_AUTHORITY", DEFAULT_AUTHORITY)
    state_dir = _state_dir()
    token_path = state_dir / "token.json"

    app = msal.PublicClientApplication(client_id, authority=authority)
    flow = app.initiate_device_flow(scopes=DEFAULT_SCOPES)
    if "user_code" not in flow:
        sys.exit(f"device flow init failed: {flow}")

    print(f"\nVisit:  {flow['verification_uri']}")
    print(f"Code:   {flow['user_code']}\n")
    print("Polling for completion (sign in, approve, then come back here)...")

    res = app.acquire_token_by_device_flow(flow)
    if "access_token" not in res:
        sys.exit(f"auth failed: {res}")

    res["_expires_at"] = time.time() + res.get("expires_in", 3600)
    token_path.write_text(json.dumps(res, indent=2))
    token_path.chmod(0o600)
    print(f"\nOK. Token written to {token_path} (mode 600).")
    print("Refresh token lifetime is ~90 days. The CLI auto-refreshes the access token.")


if __name__ == "__main__":
    main()
