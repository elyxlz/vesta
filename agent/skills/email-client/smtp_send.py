#!/usr/bin/env python3
"""SMTP send via XOAUTH2 or plain LOGIN (for app-password providers).

Provider host/port and auth strategy come from the resolved provider
profile. The user can override host/port via ``EMAIL_CLIENT_SMTP_HOST``
and ``EMAIL_CLIENT_SMTP_PORT``. Multi-account: pass ``--account <name>``
to send from a specific account; without it the daemon's default
account is used.

Reply threading: pass ``--reply-to-uid <uid>`` (and optionally
``--reply-folder <folder>``, default ``INBOX``) to fetch the original
message via IMAP and chain a proper reply. The outbound message gets
``In-Reply-To`` and ``References`` headers, a ``Re:`` subject, the
original sender as default recipient, and a quoted version of the
original body appended below the user's text. Suppress the quote with
``--no-quote``.

Forward: pass ``--forward-uid <uid>`` (and optionally
``--forward-folder <folder>``, default ``INBOX``) to fetch an existing
message and build a forward of it. The outbound subject is
``Fwd: <original-subject>`` (no double prefix); body is the user's
``--body`` plus the original headers and body inlined as a quote. A
forward starts a new thread (no ``In-Reply-To`` / ``References``) and
``--to`` is required.

CC and BCC: pass ``--cc`` and ``--bcc`` (each repeatable) to add
recipients. On replies the original CC list is preserved unless the
user passes ``--cc`` explicitly, in which case the explicit list wins.
"""
from __future__ import annotations

import argparse
import base64
import os
import re as _re
import smtplib
import sys
from email import message_from_bytes
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import (  # noqa: E402
    _decode,
    _env,
    account_profile,
    account_user,
    connect,
    get_access_token,
    get_app_password,
    resolve_account,
)


def _extract_plain_body(msg) -> str:
    """Return the best-effort plain-text body of a parsed email.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                return payload.decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                return payload.decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def _from_address(from_header: str) -> str:
    """Extract the bare email from a From header (e.g. ``Foo <a@b>`` becomes ``a@b``)."""
    if not from_header:
        return ""
    m = _re.search(r"<([^>]+)>", from_header)
    if m:
        return m.group(1).strip()
    return from_header.strip()


def _re_subject(subject: str) -> str:
    """Prefix ``Re:`` to a subject without doubling up an existing prefix."""
    s = (subject or "").strip()
    if _re.match(r"^(re|RE|Re)\s*:", s) or s.lower().startswith("re :"):
        return s or "Re:"
    return f"Re: {s}" if s else "Re:"


def _fwd_subject(subject: str) -> str:
    """Prefix ``Fwd:`` to a subject without doubling up an existing prefix."""
    s = (subject or "").strip()
    if _re.match(r"^(fwd|FWD|Fwd|fw|FW|Fw)\s*:", s):
        return s or "Fwd:"
    return f"Fwd: {s}" if s else "Fwd:"


def _forward_block(orig: dict) -> str:
    """Return the inlined original message block for a forward."""
    headers = (
        f"From: {orig.get('from', '')}\n"
        f"Date: {orig.get('date', '')}\n"
        f"Subject: {orig.get('subject', '')}\n"
        f"To: {orig.get('to', '')}\n"
    )
    cc = orig.get("cc") or ""
    if cc:
        headers += f"Cc: {cc}\n"
    body = orig.get("body", "") or ""
    return (
        "\n\n---------- Forwarded message ----------\n"
        + headers
        + "\n"
        + body
        + "\n"
    )


def _quote_body(body: str, from_header: str, date_header: str) -> str:
    """Return the quoted reply chunk: separator + ``> ``-prefixed lines."""
    sender = (from_header or "").strip() or "the sender"
    when = (date_header or "").strip() or "an earlier date"
    lines = (body or "").splitlines() or [""]
    quoted = "\n".join(f"> {ln}" for ln in lines)
    return f"\n\nOn {when}, {sender} wrote:\n{quoted}\n"


def fetch_original(
    account: str | None, folder: str, uid: str
) -> dict:
    """Fetch the original message by UID from the given folder.

    Returns a dict with ``message_id``, ``references``, ``from``, ``subject``,
    ``date``, ``body``. Raises SystemExit on missing UID.
    """
    M = connect(account)
    try:
        M.select(f'"{folder}"', readonly=True)
        typ, data = M.uid("FETCH", uid, "(RFC822)")
        if not data or not data[0]:
            sys.exit(f"reply-to-uid {uid!r} not found in folder {folder!r}")
        raw = data[0][1]
    finally:
        try:
            M.logout()
        except Exception:
            pass
    parsed = message_from_bytes(raw)
    return {
        "message_id": (parsed.get("Message-ID") or "").strip(),
        "references": (parsed.get("References") or "").strip(),
        "from": _decode(parsed.get("From")),
        "to": _decode(parsed.get("To")),
        "cc": _decode(parsed.get("Cc")),
        "subject": _decode(parsed.get("Subject")),
        "date": parsed.get("Date") or "",
        "body": _extract_plain_body(parsed),
    }


def send(
    to: str | None,
    subject: str | None,
    body: str,
    from_name: str | None = None,
    account: str | None = None,
    *,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    reply_to_uid: str | None = None,
    reply_folder: str = "INBOX",
    forward_uid: str | None = None,
    forward_folder: str = "INBOX",
    quote: bool = True,
    dry_run: bool = False,
) -> None:
    if reply_to_uid and forward_uid:
        sys.exit("--reply-to-uid and --forward-uid are mutually exclusive")
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

    cc_list = list(cc or [])
    bcc_list = list(bcc or [])
    cc_explicit = cc is not None and len(cc) > 0

    in_reply_to = ""
    references = ""
    if reply_to_uid:
        orig = fetch_original(acc, reply_folder, reply_to_uid)
        if not orig["message_id"]:
            sys.exit(
                f"original message uid={reply_to_uid} has no Message-ID header; "
                "cannot thread a reply"
            )
        in_reply_to = orig["message_id"]
        chain = (orig["references"] + " " + orig["message_id"]).strip()
        references = _re.sub(r"\s+", " ", chain)
        if subject is None:
            subject = _re_subject(orig["subject"])
        if to is None:
            sender_addr = _from_address(orig["from"])
            if not sender_addr:
                sys.exit(
                    "cannot default --to from the original message; no usable From header"
                )
            to = sender_addr
        if not cc_explicit and orig.get("cc"):
            cc_list = [c.strip() for c in orig["cc"].split(",") if c.strip()]
        if quote:
            body = (body or "") + _quote_body(orig["body"], orig["from"], orig["date"])

    if forward_uid:
        orig = fetch_original(acc, forward_folder, forward_uid)
        if subject is None:
            subject = _fwd_subject(orig["subject"])
        if to is None:
            sys.exit("--to is required when forwarding")
        if quote:
            body = (body or "") + _forward_block(orig)

    if to is None:
        sys.exit("--to is required when not replying")
    if subject is None:
        sys.exit("--subject is required when not replying")

    msg = EmailMessage()
    msg["From"] = f"{display} <{user}>"
    msg["To"] = to
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    if bcc_list:
        msg["Bcc"] = ", ".join(bcc_list)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    msg.set_content(body)

    if dry_run:
        print("--- DRY RUN: message that would be sent ---")
        print(msg.as_string())
        print("--- end dry run ---")
        return

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
    ap.add_argument(
        "--to",
        default=None,
        help="recipient (required unless --reply-to-uid is set, in which "
        "case the original sender is the default)",
    )
    ap.add_argument(
        "--cc",
        action="append",
        default=None,
        help="CC recipient; pass multiple times for multiple addresses",
    )
    ap.add_argument(
        "--bcc",
        action="append",
        default=None,
        help="BCC recipient; pass multiple times for multiple addresses",
    )
    ap.add_argument(
        "--subject",
        default=None,
        help="subject (required unless --reply-to-uid is set, in which "
        "case the original subject prefixed with Re: is the default)",
    )
    ap.add_argument("--body", required=True)
    ap.add_argument("--from-name", default=None)
    ap.add_argument(
        "--account",
        default=None,
        help="account name (defaults to accounts.json default)",
    )
    ap.add_argument(
        "--reply-to-uid",
        default=None,
        help="UID of an existing message to thread this reply to "
        "(fetched via IMAP from --reply-folder)",
    )
    ap.add_argument(
        "--reply-folder",
        default="INBOX",
        help="folder to fetch the original message from (default INBOX)",
    )
    ap.add_argument(
        "--forward-uid",
        default=None,
        help="UID of an existing message to forward "
        "(fetched via IMAP from --forward-folder); requires --to",
    )
    ap.add_argument(
        "--forward-folder",
        default="INBOX",
        help="folder to fetch the forwarded original from (default INBOX)",
    )
    ap.add_argument(
        "--no-quote",
        action="store_true",
        help="suppress the quoted original body when replying or forwarding",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the would-send message and exit without contacting SMTP",
    )
    args = ap.parse_args()
    send(
        args.to,
        args.subject,
        args.body,
        args.from_name,
        account=args.account,
        cc=args.cc,
        bcc=args.bcc,
        reply_to_uid=args.reply_to_uid,
        reply_folder=args.reply_folder,
        forward_uid=args.forward_uid,
        forward_folder=args.forward_folder,
        quote=not args.no_quote,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
