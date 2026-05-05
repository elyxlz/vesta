#!/usr/bin/env python3
"""IMAP client over OAuth2 (XOAUTH2) or app-password basic auth.

Supports multiple providers (Microsoft personal, Gmail, Yahoo, iCloud,
Fastmail, generic IMAP) via the profile registry in ``providers.py``.

Provider is auto-detected from the user's email domain, or pinned via
``IMAP_MAIL_PROVIDER`` (or the ``--provider`` flag on ``auth.py``).

Environment overrides (set in ``~/.bashrc``):
    IMAP_MAIL_USER             email address (required)
    IMAP_MAIL_PROVIDER         force provider key (e.g. ``gmail``)
    IMAP_MAIL_DIR              token + state dir (default ~/.imap-mail)
    IMAP_MAIL_HOST             override IMAP host
    IMAP_MAIL_SMTP_HOST        override SMTP host
    IMAP_MAIL_SMTP_PORT        override SMTP port
    IMAP_MAIL_OAUTH_CLIENT_ID  override OAuth client ID
    IMAP_MAIL_OAUTH_AUTHORITY  override OAuth authority (Microsoft only)
    IMAP_MAIL_OAUTH_SCOPES     override scope list (whitespace-separated)
    IMAP_MAIL_FROM_NAME        display name on outbound mail
    IMAP_MAIL_POLL_INTERVAL    daemon poll seconds

Backwards compatibility: a token file written by the v0.1 Microsoft-only
release (no ``provider`` key) is treated as ``microsoft-personal``.
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
import urllib.parse
import urllib.request
from email import message_from_bytes
from email.header import decode_header

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from providers import (  # noqa: E402
    THUNDERBIRD_MS_CLIENT_ID,
    get_profile,
    resolve_provider,
)

# Re-exported for backwards compatibility with tools that imported these
# names from the v0.1 release.
THUNDERBIRD_CLIENT_ID = THUNDERBIRD_MS_CLIENT_ID
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


def load_token() -> dict | None:
    p = _token_path()
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_token(tok: dict) -> None:
    p = _token_path()
    p.write_text(json.dumps(tok, indent=2))
    p.chmod(0o600)


def current_profile() -> tuple[str, dict]:
    """Resolve the active provider name and profile.

    If a token exists and pins a provider, that wins over auto-detect
    (so the daemon doesn't get reconfigured by an env-var change after
    the user already authenticated against a specific provider).
    """
    tok = load_token()
    if tok and tok.get("provider"):
        name = tok["provider"]
        try:
            profile = get_profile(name)
        except KeyError:
            # Unknown provider in token (corrupt or future format):
            # fall back to env-driven resolution.
            return resolve_provider(dict(os.environ))
        # Still let env overrides apply on top of the pinned profile.
        from providers import apply_env_overrides
        return name, apply_env_overrides(profile, dict(os.environ))
    return resolve_provider(dict(os.environ))


def _refresh_microsoft(tok: dict, profile: dict) -> dict:
    import msal

    rt = tok.get("refresh_token")
    if not rt:
        sys.exit("no refresh_token in cached token; re-run auth")
    app = msal.PublicClientApplication(
        profile["oauth_client_id"], authority=profile["oauth_authority"]
    )
    res = app.acquire_token_by_refresh_token(rt, scopes=profile["oauth_scopes"])
    if "access_token" not in res:
        sys.exit(f"refresh failed: {res}")
    res["_expires_at"] = time.time() + res.get("expires_in", 3600)
    res["provider"] = tok.get("provider", "microsoft-personal")
    res["user"] = tok.get("user") or _env("IMAP_MAIL_USER")
    return res


def _refresh_google(tok: dict, profile: dict) -> dict:
    rt = tok.get("refresh_token")
    if not rt:
        sys.exit("no refresh_token in cached token; re-run auth")
    data = urllib.parse.urlencode(
        {
            "client_id": profile["oauth_client_id"],
            "refresh_token": rt,
            "grant_type": "refresh_token",
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
        sys.exit(f"refresh failed: {res}")
    res["refresh_token"] = res.get("refresh_token", rt)
    res["_expires_at"] = time.time() + res.get("expires_in", 3600)
    res["provider"] = tok.get("provider", "gmail")
    res["user"] = tok.get("user") or _env("IMAP_MAIL_USER")
    return res


def get_access_token(scopes: list[str] | None = None) -> str:
    """Return a fresh OAuth2 access token for the active provider.

    Only meaningful for OAuth providers (microsoft-personal, gmail).
    For app-password providers, callers should use :func:`get_app_password`.
    The ``scopes`` argument is accepted for backwards compatibility and
    ignored when the provider profile already specifies its scopes.
    """
    name, profile = current_profile()
    strategy = profile["auth_strategy"]
    tok = load_token()
    if tok is None:
        sys.exit(
            f"no token at {_token_path()}; run auth first "
            f"(uv run python3 ~/agent/skills/imap-mail/auth.py)"
        )
    if strategy == "app-password":
        sys.exit(
            f"provider {name} uses app-password auth; "
            "get_access_token() is not applicable"
        )
    expires_at = tok.get("_expires_at", 0)
    if time.time() < expires_at - 60 and tok.get("access_token"):
        return tok["access_token"]
    if strategy == "device-flow":
        new = _refresh_microsoft(tok, profile)
    elif strategy == "loopback-oauth":
        new = _refresh_google(tok, profile)
    else:
        sys.exit(f"unsupported auth strategy {strategy!r}")
    save_token(new)
    return new["access_token"]


def get_app_password() -> str:
    tok = load_token()
    if tok is None:
        sys.exit(
            f"no credential at {_token_path()}; run auth first "
            f"(uv run python3 ~/agent/skills/imap-mail/auth.py)"
        )
    pw = tok.get("app_password")
    if not pw:
        sys.exit("no app_password in token; re-run auth for this provider")
    return pw


def connect() -> imaplib.IMAP4_SSL:
    user = _env("IMAP_MAIL_USER", required=True)
    name, profile = current_profile()
    host = profile["imap_host"]
    port = int(profile.get("imap_port", 993))
    if not host:
        sys.exit(
            f"provider {name} has no IMAP host configured; "
            "set IMAP_MAIL_HOST in ~/.bashrc"
        )
    M = imaplib.IMAP4_SSL(host, port)
    if profile["auth_strategy"] == "app-password":
        pw = get_app_password()
        M.login(user, pw)
    else:
        access = get_access_token()
        auth = f"user={user}\x01auth=Bearer {access}\x01\x01".encode()
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


# Compatibility shim. Older callers may import _detect_provider from
# this module; keep the symbol live and forward to providers.py.
def _detect_provider(email: str) -> str | None:
    from providers import detect_provider
    return detect_provider(email)


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
