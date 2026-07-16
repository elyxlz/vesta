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

HTML body: pass ``--body-html <html>`` instead of (or alongside)
``--body``. With both, the message is multipart/alternative carrying
both parts. With only HTML, a stripped plain-text fallback is
synthesized so non-HTML clients still see something.

Attachments: pass ``--attach <path>`` (repeatable) to attach files.
MIME type is guessed from the file extension via ``mimetypes``, with
``application/octet-stream`` as fallback. Total attachment size is
capped at 25 MB (most providers reject larger); the send aborts with
a clear error if exceeded.

Sent folder sync: by default the message is IMAP-APPENDed to the
provider's Sent folder after a successful SMTP send so it shows up in
the user's mail UI. Skip with ``--no-sent-sync``. The Sent (and Drafts)
folder is resolved from the server's RFC 6154 SPECIAL-USE attribute,
falling back to the provider profile then a default name.

Drafts: pass ``--draft`` to APPEND the composed message to the Drafts
folder with the ``\\Draft`` flag instead of sending it. Works with
``--reply-to-uid`` / ``--forward-uid`` so a threaded reply or forward
can be drafted for the user to review and send from any mail client.
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import mimetypes
import os
import pathlib
import re as _re
import smtplib
import sys
import time
from email.message import EmailMessage

from imap_tools import AND, MailMessageFlags

# Most providers (Gmail, Microsoft, Yahoo) reject messages larger than
# 25 MB. Cap the combined attachment size at this limit so we fail
# clearly before SMTP rejects us mid-conversation.
MAX_ATTACH_TOTAL_BYTES = 25 * 1024 * 1024

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib

from imap_client import (
    _env,
    _from_full,
    _to_full,
    account_profile,
    account_user,
    connect,
    get_access_token,
    get_app_password,
    resolve_account,
    resolve_special_folder,
)

_DRAFT_ONLY_MESSAGE = "draft-only mode (EMAIL_DRAFT_ONLY): sending is disabled. Create a draft instead (--draft / the draft command)."


def _draft_only_enabled() -> bool:
    """True when EMAIL_DRAFT_ONLY is set to a truthy value (1/true/yes, case-insensitive)."""
    return os.environ.get("EMAIL_DRAFT_ONLY", "").strip().lower() in {"1", "true", "yes"}


def _from_address(from_header: str) -> str:
    """Extract the bare email from a From header (e.g. ``Foo <a@b>`` becomes ``a@b``)."""
    m = _re.search(r"<([^>]+)>", from_header or "")
    if m:
        return m.group(1).strip()
    return (from_header or "").strip()


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


def _quote_body(body: str, from_header: str, date_header: str) -> str:
    """Return the quoted reply chunk: separator + ``> ``-prefixed lines."""
    sender = (from_header or "").strip() or "the sender"
    when = (date_header or "").strip() or "an earlier date"
    lines = (body or "").splitlines() or [""]
    quoted = "\n".join(f"> {ln}" for ln in lines)
    return f"\n\nOn {when}, {sender} wrote:\n{quoted}\n"


def _forward_block(orig: dict) -> str:
    """Return the inlined original message block for a forward."""
    headers = f"From: {orig.get('from', '')}\nDate: {orig.get('date', '')}\nSubject: {orig.get('subject', '')}\nTo: {orig.get('to', '')}\n"
    cc = orig.get("cc") or ""
    if cc:
        headers += f"Cc: {cc}\n"
    body = orig.get("body", "") or ""
    return "\n\n---------- Forwarded message ----------\n" + headers + "\n" + body + "\n"


def _strip_html(html: str) -> str:
    """Crude HTML to plain-text fallback for the alt part of an HTML-only send."""
    s = _re.sub(r"<\s*(br|/p|/div|/li|/h[1-6])\s*/?\s*>", "\n", html or "", flags=_re.IGNORECASE)
    s = _re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    return _re.sub(r"\n{3,}", "\n\n", s).strip()


def fetch_original(account: str | None, folder: str, uid: str) -> dict:
    """Fetch the original message by UID from the given folder.

    Returns a dict with ``message_id``, ``references``, ``from``, ``to``,
    ``cc``, ``subject``, ``date``, ``body``. Raises SystemExit on
    missing UID.
    """
    with connect(account, initial_folder=None) as mb:
        mb.folder.set(folder)
        msgs = list(mb.fetch(AND(uid=uid), mark_seen=False, limit=1))
        if not msgs:
            sys.exit(f"uid {uid!r} not found in folder {folder!r}")
        m = msgs[0]
    cc = ", ".join(a.full for a in m.cc_values) if m.cc_values else ""
    return {
        "message_id": (m.headers.get("message-id", ("",))[0] or "").strip(),
        "references": (m.headers.get("references", ("",))[0] or "").strip(),
        "from": _from_full(m),
        "to": _to_full(m),
        "cc": cc,
        "subject": m.subject,
        "date": m.date_str,
        "body": m.text or m.html or "",
    }


def _append_message(
    account: str | None,
    raw_bytes: bytes,
    *,
    role: str,
    profile_fallback: str | None,
    flags: list[str],
) -> tuple[bool, str]:
    """IMAP-APPEND a message into the ``role`` special-use folder.

    The folder is resolved via the server's SPECIAL-USE attribute, then
    ``profile_fallback``, then a role default. Returns (ok, info) and never
    raises: the SMTP send (or draft intent) is independent of the copy.
    """
    try:
        mb = connect(account, initial_folder=None)
    except Exception as e:
        return False, f"connect failed: {e}"
    try:
        folder = resolve_special_folder(mb, role, profile_fallback)
        try:
            mb.append(
                raw_bytes,
                folder=folder,
                dt=_dt.datetime.fromtimestamp(time.time(), tz=_dt.UTC),
                flag_set=flags,
            )
            return True, folder
        except Exception as e:
            return False, f"APPEND to {folder!r} failed: {e}"
    finally:
        with contextlib.suppress(Exception):
            mb.logout()


def _load_attachments(paths: list[str] | None) -> list[dict]:
    """Read each attachment path, guess MIME type, enforce size cap.

    Returns a list of ``{name, maintype, subtype, data}`` dicts. Exits
    with a clear error if any path is missing or if the combined size
    exceeds ``MAX_ATTACH_TOTAL_BYTES``.
    """
    if not paths:
        return []
    out: list[dict] = []
    total = 0
    for raw in paths:
        p = pathlib.Path(raw).expanduser()
        if not p.exists():
            sys.exit(f"attachment not found: {raw}")
        if not p.is_file():
            sys.exit(f"attachment is not a regular file: {raw}")
        try:
            data = p.read_bytes()
        except OSError as e:
            sys.exit(f"failed to read attachment {raw}: {e}")
        total += len(data)
        if total > MAX_ATTACH_TOTAL_BYTES:
            mb = total / (1024 * 1024)
            cap_mb = MAX_ATTACH_TOTAL_BYTES / (1024 * 1024)
            sys.exit(f"attachments too large: {mb:.1f} MB exceeds {cap_mb:.0f} MB cap (most providers reject larger messages); aborting send")
        guess, _enc = mimetypes.guess_type(p.name)
        if not guess:
            maintype, subtype = "application", "octet-stream"
        else:
            maintype, _, subtype = guess.partition("/")
            if not subtype:
                maintype, subtype = "application", "octet-stream"
        out.append(
            {
                "name": p.name,
                "maintype": maintype,
                "subtype": subtype,
                "data": data,
            }
        )
    return out


def _build_message(
    *,
    user: str,
    display: str,
    to: str,
    subject: str,
    body: str,
    body_html: str | None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    in_reply_to: str = "",
    references: str = "",
    attachments: list[dict] | None = None,
) -> EmailMessage:
    """Assemble the outbound EmailMessage from parts."""
    msg = EmailMessage()
    msg["From"] = f"{display} <{user}>"
    msg["To"] = to
    if cc:
        msg["Cc"] = ", ".join(cc)
    if bcc:
        msg["Bcc"] = ", ".join(bcc)
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    if body and body_html:
        msg.set_content(body)
        msg.add_alternative(body_html, subtype="html")
    elif body_html:
        msg.set_content(_strip_html(body_html) or " ")
        msg.add_alternative(body_html, subtype="html")
    else:
        msg.set_content(body or "")
    for att in attachments or []:
        msg.add_attachment(
            att["data"],
            maintype=att["maintype"],
            subtype=att["subtype"],
            filename=att["name"],
        )
    return msg


def send(
    to: str | None,
    subject: str | None,
    body: str,
    from_name: str | None = None,
    account: str | None = None,
    *,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    body_html: str | None = None,
    reply_to_uid: str | None = None,
    reply_folder: str = "INBOX",
    forward_uid: str | None = None,
    forward_folder: str = "INBOX",
    attach: list[str] | None = None,
    quote: bool = True,
    sent_sync: bool = True,
    dry_run: bool = False,
    draft: bool = False,
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
            sys.exit(f"original message uid={reply_to_uid} has no Message-ID header; cannot thread a reply")
        in_reply_to = orig["message_id"]
        chain = (orig["references"] + " " + orig["message_id"]).strip()
        references = _re.sub(r"\s+", " ", chain)
        if subject is None:
            subject = _re_subject(orig["subject"])
        if to is None:
            sender_addr = _from_address(orig["from"])
            if not sender_addr:
                sys.exit("cannot default --to from the original message; no usable From header")
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
    if not body and not body_html:
        sys.exit("at least one of --body / --body-html must produce content")

    attachments = _load_attachments(attach)

    msg = _build_message(
        user=user,
        display=display,
        to=to,
        subject=subject,
        body=body,
        body_html=body_html,
        cc=cc_list,
        bcc=bcc_list,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
    )

    if dry_run:
        verb = "saved as a draft" if draft else "sent"
        print(f"--- DRY RUN: message that would be {verb} ---")
        print(msg.as_string())
        print("--- end dry run ---")
        if draft:
            print("--- DRY RUN: would IMAP APPEND to the Drafts folder ---")
        elif sent_sync:
            print("--- DRY RUN: would IMAP APPEND to the Sent folder ---")
        return

    if draft:
        # Save to Drafts instead of sending. Reply/forward threading headers
        # are kept so the user can review and send it from any mail client.
        ok, info = _append_message(
            acc,
            msg.as_bytes(),
            role="drafts",
            profile_fallback=None,
            flags=[MailMessageFlags.DRAFT, MailMessageFlags.SEEN],
        )
        if ok:
            print(f"draft saved to {info}")
            return
        sys.exit(f"draft save failed: {info}")

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
        auth_b64 = base64.b64encode(f"user={user}\x01auth=Bearer {access}\x01\x01".encode()).decode()
        code, resp = s.docmd("AUTH", f"XOAUTH2 {auth_b64}")
        if code == 334:
            code, resp = s.docmd("")
        if code != 235:
            s.quit()
            sys.exit(f"smtp auth failed: {code} {resp!r}")

    s.send_message(msg)
    s.quit()
    print("OK")

    if reply_to_uid:
        # Flag the original \Answered so every client shows the replied-to
        # indicator. Non-fatal: the reply already went out.
        try:
            with connect(acc, initial_folder=None) as mb:
                mb.folder.set(reply_folder)
                mb.flag(reply_to_uid, MailMessageFlags.ANSWERED, True)
            print(f"marked uid {reply_to_uid} \\Answered")
        except Exception as e:
            print(
                f"warning: could not mark original \\Answered ({e})",
                file=sys.stderr,
            )

    if sent_sync:
        # Strip Bcc before APPEND (those addresses must not appear in
        # the stored copy that the user can later read in their mail UI).
        copy = _build_message(
            user=user,
            display=display,
            to=to,
            subject=subject,
            body=body,
            body_html=body_html,
            cc=cc_list,
            bcc=None,
            in_reply_to=in_reply_to,
            references=references,
            attachments=attachments,
        )
        sent_fallback = profile["sent_folder"] if "sent_folder" in profile else None
        ok, info = _append_message(
            acc,
            copy.as_bytes(),
            role="sent",
            profile_fallback=sent_fallback,
            flags=[MailMessageFlags.SEEN],
        )
        if ok:
            print(f"appended to {info}")
        else:
            print(f"warning: sent-sync skipped ({info})", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--to",
        default=None,
        help="recipient (required unless --reply-to-uid is set, in which case the original sender is the default)",
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
        help="subject (required unless --reply-to-uid is set, in which case the original subject prefixed with Re: is the default)",
    )
    ap.add_argument(
        "--body",
        default="",
        help="plain-text body (required unless --body-html is given)",
    )
    ap.add_argument(
        "--body-html",
        default=None,
        help="HTML body; combine with --body for multipart/alternative",
    )
    ap.add_argument("--from-name", default=None)
    ap.add_argument(
        "--account",
        default=None,
        help="account name (defaults to accounts.json default)",
    )
    ap.add_argument(
        "--reply-to-uid",
        default=None,
        help="UID of an existing message to thread this reply to (fetched via IMAP from --reply-folder)",
    )
    ap.add_argument(
        "--reply-folder",
        default="INBOX",
        help="folder to fetch the original message from (default INBOX)",
    )
    ap.add_argument(
        "--forward-uid",
        default=None,
        help="UID of an existing message to forward (fetched via IMAP from --forward-folder); requires --to",
    )
    ap.add_argument(
        "--forward-folder",
        default="INBOX",
        help="folder to fetch the forwarded original from (default INBOX)",
    )
    ap.add_argument(
        "--attach",
        action="append",
        default=None,
        metavar="PATH",
        help="attach a file; pass multiple times for multiple attachments. Total size capped at 25 MB",
    )
    ap.add_argument(
        "--no-quote",
        action="store_true",
        help="suppress the quoted original body when replying or forwarding",
    )
    ap.add_argument(
        "--no-sent-sync",
        action="store_true",
        help="skip IMAP APPEND of the sent message into the Sent folder",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print the would-send message and exit without contacting SMTP",
    )
    ap.add_argument(
        "--draft",
        action="store_true",
        help="save the composed message to the Drafts folder instead of sending; works with --reply-to-uid / --forward-uid to draft for review",
    )
    args = ap.parse_args()
    # Hard draft-only guard: refuse any transmitting invocation (send/reply/forward)
    # before touching SMTP. Drafting (--draft) and the no-network preview (--dry-run)
    # stay allowed. Default off: no behavior change when EMAIL_DRAFT_ONLY is unset.
    if _draft_only_enabled() and not args.draft and not args.dry_run:
        sys.exit(_DRAFT_ONLY_MESSAGE)
    send(
        args.to,
        args.subject,
        args.body,
        args.from_name,
        account=args.account,
        cc=args.cc,
        bcc=args.bcc,
        body_html=args.body_html,
        reply_to_uid=args.reply_to_uid,
        reply_folder=args.reply_folder,
        forward_uid=args.forward_uid,
        forward_folder=args.forward_folder,
        attach=args.attach,
        quote=not args.no_quote,
        sent_sync=not args.no_sent_sync,
        dry_run=args.dry_run,
        draft=args.draft,
    )


if __name__ == "__main__":
    main()
