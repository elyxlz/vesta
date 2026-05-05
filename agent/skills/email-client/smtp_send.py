#!/usr/bin/env python3
"""SMTP send via XOAUTH2 or plain LOGIN (for app-password providers).

Provider host/port and auth strategy come from the resolved provider
profile. The user can override host/port via ``EMAIL_CLIENT_SMTP_HOST``
and ``EMAIL_CLIENT_SMTP_PORT``. Multi-account: pass ``--account <name>``
to send from a specific account; without it the daemon's default
account is used.
"""
from __future__ import annotations

import argparse
import base64
import os
import smtplib
import sys
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import (  # noqa: E402
    _env,
    account_profile,
    account_user,
    get_access_token,
    get_app_password,
    resolve_account,
)


def send(
    to: str,
    subject: str,
    body: str,
    from_name: str | None = None,
    account: str | None = None,
) -> None:
    acc = resolve_account(account)
    user = account_user(acc)
    name, profile = account_profile(acc)
    smtp_host = profile.get("smtp_host")
    smtp_port = int(profile.get("smtp_port", 587))
    if not smtp_host:
        sys.exit(
            f"provider {name} (account {acc!r}) has no SMTP host configured; "
            "set smtp_host in the per-account config.json or EMAIL_CLIENT_SMTP_HOST"
        )
    display = from_name or _env("EMAIL_CLIENT_FROM_NAME", user.split("@", 1)[0])

    msg = EmailMessage()
    msg["From"] = f"{display} <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    s = smtplib.SMTP(smtp_host, smtp_port)
    s.ehlo()
    if profile.get("smtp_starttls", True):
        s.starttls()
        s.ehlo()

    if profile["auth_strategy"] == "app-password":
        pw = get_app_password(acc)
        try:
            s.login(user, pw)
        except smtplib.SMTPAuthenticationError as e:
            s.quit()
            sys.exit(f"smtp auth failed: {e}")
    else:
        access = get_access_token(acc)
        auth_b64 = base64.b64encode(
            f"user={user}\x01auth=Bearer {access}\x01\x01".encode()
        ).decode()
        code, resp = s.docmd("AUTH", f"XOAUTH2 {auth_b64}")
        if code == 334:
            code, resp = s.docmd("")
        if code != 235:
            s.quit()
            sys.exit(f"smtp auth failed: {code} {resp!r}")

    s.send_message(msg)
    s.quit()
    print("OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body", required=True)
    ap.add_argument("--from-name", default=None)
    ap.add_argument(
        "--account",
        default=None,
        help="account name (defaults to accounts.json default)",
    )
    args = ap.parse_args()
    send(args.to, args.subject, args.body, args.from_name, account=args.account)


if __name__ == "__main__":
    main()
