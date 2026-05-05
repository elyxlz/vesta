#!/usr/bin/env python3
"""IMAP client over OAuth2 (XOAUTH2).

Defaults target personal Microsoft accounts (Hotmail, Outlook.com, Live)
via Mozilla Thunderbird's public OAuth client ID, which is the standard
workaround for "tenantless app registrations are deprecated".

Environment overrides (set in ~/.bashrc):
    IMAP_MAIL_USER             email address (required)
    IMAP_MAIL_DIR              token + state dir (default ~/.imap-mail)
    IMAP_MAIL_HOST             default outlook.office365.com
    IMAP_MAIL_OAUTH_CLIENT_ID  default Thunderbird's public ID
    IMAP_MAIL_OAUTH_AUTHORITY  default https://login.microsoftonline.com/consumers
"""
from __future__ import annotations

import argparse
import imaplib
import json
import os
import pathlib
import re
import sys
import time
from email import message_from_bytes
from email.header import decode_header

import msal

THUNDERBIRD_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"
DEFAULT_AUTHORITY = "https://login.microsoftonline.com/consumers"
DEFAULT_HOST = "outlook.office365.com"
DEFAULT_SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
]


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"missing required env var {name}")
    return val or ""


def _state_dir() -> pathlib.Path:
    d = pathlib.Path(_env("IMAP_MAIL_DIR", str(pathlib.Path.home() / ".imap-mail")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _token_path() -> pathlib.Path:
    return _state_dir() / "token.json"


def get_access_token(scopes: list[str] | None = None) -> str:
    scopes = scopes or DEFAULT_SCOPES
    tok_path = _token_path()
    if not tok_path.exists():
        sys.exit(
            f"no token at {tok_path}; run device-flow auth first "
            f"(uv run python3 ~/agent/skills/imap-mail/auth.py)"
        )
    tok = json.loads(tok_path.read_text())
    expires_at = tok.get("_expires_at", 0)
    if time.time() < expires_at - 60 and tok.get("access_token"):
        return tok["access_token"]
    rt = tok.get("refresh_token")
    if not rt:
        sys.exit("no refresh_token in cached token; re-run device flow")
    client_id = _env("IMAP_MAIL_OAUTH_CLIENT_ID", THUNDERBIRD_CLIENT_ID)
    authority = _env("IMAP_MAIL_OAUTH_AUTHORITY", DEFAULT_AUTHORITY)
    app = msal.PublicClientApplication(client_id, authority=authority)
    res = app.acquire_token_by_refresh_token(rt, scopes=scopes)
    if "access_token" not in res:
        sys.exit(f"refresh failed: {res}")
    res["_expires_at"] = time.time() + res.get("expires_in", 3600)
    tok_path.write_text(json.dumps(res, indent=2))
    tok_path.chmod(0o600)
    return res["access_token"]


def connect() -> imaplib.IMAP4_SSL:
    user = _env("IMAP_MAIL_USER", required=True)
    host = _env("IMAP_MAIL_HOST", DEFAULT_HOST)
    access = get_access_token()
    auth = f"user={user}\x01auth=Bearer {access}\x01\x01".encode()
    M = imaplib.IMAP4_SSL(host, 993)
    M.authenticate("XOAUTH2", lambda _: auth)
    return M


def _decode(s: str | None) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    out = []
    for text, enc in parts:
        if isinstance(text, bytes):
            out.append(text.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def cmd_folders(_args):
    M = connect()
    typ, folders = M.list()
    for f in folders:
        print(f.decode(errors="replace"))
    M.logout()


def cmd_list(args):
    M = connect()
    M.select(f'"{args.folder}"', readonly=True)
    typ, data = M.search(None, "ALL")
    ids = data[0].split()
    if args.limit:
        ids = ids[-args.limit :]
    if not ids:
        print("[]")
        M.logout()
        return
    seq = b",".join(ids)
    typ, msgs = M.fetch(seq, "(UID RFC822.HEADER)")
    out = []
    for item in msgs:
        if not isinstance(item, tuple):
            continue
        meta = item[0].decode(errors="replace")
        m_uid = re.search(r"UID (\d+)", meta)
        uid = m_uid.group(1) if m_uid else None
        h = message_from_bytes(item[1])
        out.append(
            {
                "uid": uid,
                "from": _decode(h.get("From")),
                "to": _decode(h.get("To")),
                "subject": _decode(h.get("Subject")),
                "date": h.get("Date"),
            }
        )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    M.logout()


def cmd_get(args):
    M = connect()
    M.select(f'"{args.folder}"', readonly=True)
    typ, data = M.uid("FETCH", args.uid, "(RFC822)")
    if not data or not data[0]:
        sys.exit("not found")
    raw = data[0][1]
    h = message_from_bytes(raw)
    body = ""
    if h.is_multipart():
        for part in h.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_payload(decode=True).decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
                break
        if not body:
            for part in h.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True).decode(
                        part.get_content_charset() or "utf-8", errors="replace"
                    )
                    break
    else:
        body = h.get_payload(decode=True).decode(
            h.get_content_charset() or "utf-8", errors="replace"
        )
    print(
        json.dumps(
            {
                "from": _decode(h.get("From")),
                "to": _decode(h.get("To")),
                "subject": _decode(h.get("Subject")),
                "date": h.get("Date"),
                "body": body[: args.body_chars],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    M.logout()


def cmd_search(args):
    M = connect()
    M.select(f'"{args.folder}"', readonly=True)
    typ, data = M.search(None, args.query)
    ids = data[0].split()
    if args.limit:
        ids = ids[-args.limit :]
    if not ids:
        print("[]")
        M.logout()
        return
    seq = b",".join(ids)
    typ, msgs = M.fetch(seq, "(UID RFC822.HEADER)")
    out = []
    for item in msgs:
        if not isinstance(item, tuple):
            continue
        meta = item[0].decode(errors="replace")
        m_uid = re.search(r"UID (\d+)", meta)
        uid = m_uid.group(1) if m_uid else None
        h = message_from_bytes(item[1])
        out.append(
            {
                "uid": uid,
                "from": _decode(h.get("From")),
                "subject": _decode(h.get("Subject")),
                "date": h.get("Date"),
            }
        )
    print(json.dumps(out, indent=2, ensure_ascii=False))
    M.logout()


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list-folders")
    p = sub.add_parser("list")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("get")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--uid", required=True)
    p.add_argument("--body-chars", type=int, default=4000)
    p = sub.add_parser("search")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()
    {
        "list-folders": cmd_folders,
        "list": cmd_list,
        "get": cmd_get,
        "search": cmd_search,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
