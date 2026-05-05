#!/usr/bin/env python3
"""SMTP send via XOAUTH2.

Defaults target Microsoft personal accounts (smtp.office365.com:587 STARTTLS).
"""
from __future__ import annotations

import argparse
import base64
import os
import smtplib
import sys
from email.message import EmailMessage

# Reuse the IMAP module's token caching + env loading.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import _env, get_access_token  # noqa: E402

DEFAULT_SMTP_HOST = "smtp.office365.com"
DEFAULT_SMTP_PORT = 587


def send(to: str, subject: str, body: str, from_name: str | None = None) -> None:
    user = _env("IMAP_MAIL_USER", required=True)
    smtp_host = _env("IMAP_MAIL_SMTP_HOST", DEFAULT_SMTP_HOST)
    smtp_port = int(_env("IMAP_MAIL_SMTP_PORT", str(DEFAULT_SMTP_PORT)))
    display = from_name or _env("IMAP_MAIL_FROM_NAME", user.split("@", 1)[0])

    access = get_access_token()
    auth_b64 = base64.b64encode(
        f"user={user}\x01auth=Bearer {access}\x01\x01".encode()
    ).decode()

    msg = EmailMessage()
    msg["From"] = f"{display} <{user}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    s = smtplib.SMTP(smtp_host, smtp_port)
    s.ehlo()
    s.starttls()
    s.ehlo()
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
    args = ap.parse_args()
    send(args.to, args.subject, args.body, args.from_name)


if __name__ == "__main__":
    main()
