#!/usr/bin/env python3
"""IMAP client over OAuth2 (XOAUTH2) or app-password basic auth.

Supports multiple providers (Microsoft personal, Gmail, Yahoo, iCloud,
Fastmail, generic IMAP) via the profile registry in ``providers.py``,
and multiple accounts simultaneously via the per-account state layout
in ``$EMAIL_CLIENT_DIR/accounts/<name>/``.

Provider is auto-detected from the account's email domain, or pinned
via the per-account ``config.json`` (or ``--provider`` on ``auth.py``).

Environment overrides (set in ``~/.bashrc``):
    EMAIL_CLIENT_DIR              token + state dir (default ~/.email-client)
    EMAIL_CLIENT_HOST             override IMAP host
    EMAIL_CLIENT_SMTP_HOST        override SMTP host
    EMAIL_CLIENT_SMTP_PORT        override SMTP port
    EMAIL_CLIENT_OAUTH_CLIENT_ID  override OAuth client ID
    EMAIL_CLIENT_OAUTH_AUTHORITY  override OAuth authority (Microsoft only)
    EMAIL_CLIENT_OAUTH_SCOPES     override scope list (whitespace-separated)
    EMAIL_CLIENT_FROM_NAME        display name on outbound mail
    EMAIL_CLIENT_POLL_INTERVAL    daemon poll seconds
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
    apply_env_overrides,
    detect_provider,
    get_profile,
    resolve_provider,
)


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Read an EMAIL_CLIENT_* env var with optional default."""
    val = os.environ.get(name) or default
    if required and not val:
        sys.exit(f"missing required env var {name}")
    return val or ""


def _state_dir() -> pathlib.Path:
    """Return the top-level email-client state dir.

    Resolution order:
      1. ``$EMAIL_CLIENT_DIR``
      2. ``~/.email-client``
    """
    explicit = os.environ.get("EMAIL_CLIENT_DIR")
    if explicit:
        d = pathlib.Path(explicit)
        d.mkdir(parents=True, exist_ok=True)
        return d
    new = pathlib.Path.home() / ".email-client"
    new.mkdir(parents=True, exist_ok=True)
    return new


# -- multi-account state layout -------------------------------------


def _accounts_dir() -> pathlib.Path:
    return _state_dir() / "accounts"


def _accounts_index_path() -> pathlib.Path:
    return _state_dir() / "accounts.json"


def load_accounts_index() -> dict:
    """Return the accounts index dict, or an empty index if missing."""
    p = _accounts_index_path()
    if not p.exists():
        return {"accounts": [], "default": None}
    return json.loads(p.read_text())


def save_accounts_index(idx: dict) -> None:
    p = _accounts_index_path()
    p.write_text(json.dumps(idx, indent=2))


def list_accounts() -> list[str]:
    return list(load_accounts_index().get("accounts") or [])


def default_account() -> str | None:
    idx = load_accounts_index()
    if idx.get("default"):
        return idx["default"]
    accs = idx.get("accounts") or []
    return accs[0] if accs else None


def resolve_account(name: str | None) -> str:
    """Return the chosen account name or exit with a helpful error."""
    if name:
        if name not in list_accounts():
            sys.exit(
                f"unknown account {name!r}; known: {list_accounts()}. "
                f"Add one with: email-client auth add --account {name}"
            )
        return name
    chosen = default_account()
    if not chosen:
        sys.exit(
            "no email accounts registered; "
            "add one with: email-client auth add --account <name>"
        )
    return chosen


def account_dir(name: str) -> pathlib.Path:
    d = _accounts_dir() / name
    d.mkdir(parents=True, exist_ok=True)
    return d


# -- per-account config + token ------------------------------------


def load_config(account: str) -> dict:
    p = account_dir(account) / "config.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_config(account: str, cfg: dict) -> None:
    p = account_dir(account) / "config.json"
    p.write_text(json.dumps(cfg, indent=2))


def _token_path(account: str) -> pathlib.Path:
    return account_dir(account) / "token.json"


def load_token(account: str) -> dict | None:
    p = _token_path(account)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_token(account: str, tok: dict) -> None:
    p = _token_path(account)
    p.write_text(json.dumps(tok, indent=2))
    p.chmod(0o600)


def account_user(account: str) -> str:
    """Return the email address for an account.

    Order of precedence: per-account config.json["user"], then the
    token.json["user"] field, then the env var ``EMAIL_CLIENT_USER``.
    Errors loud if none resolves.
    """
    cfg = load_config(account)
    if cfg.get("user"):
        return cfg["user"]
    tok = load_token(account)
    if tok and tok.get("user"):
        return tok["user"]
    user = _env("EMAIL_CLIENT_USER")
    if user:
        return user
    sys.exit(
        f"no user configured for account {account!r}; "
        f"set 'user' in {account_dir(account) / 'config.json'}"
    )


def account_profile(account: str) -> tuple[str, dict]:
    """Resolve the active provider name and profile for an account.

    Order:
      1. per-account ``config.json`` ``provider`` field
      2. token-pinned provider
      3. auto-detect from the account's email domain
      4. ``microsoft-personal`` final fallback

    Env-var overrides on host/port/scopes still apply on top.
    """
    cfg = load_config(account)
    tok = load_token(account)
    name = (cfg.get("provider") or (tok.get("provider") if tok else "") or "").strip()
    if not name:
        user = (
            cfg.get("user")
            or (tok.get("user") if tok else "")
            or _env("EMAIL_CLIENT_USER")
        )
        name = detect_provider(user or "") or "microsoft-personal"
    try:
        profile = get_profile(name)
    except KeyError:
        return resolve_provider(dict(os.environ))
    # Layer per-account config overrides, then env overrides, on top.
    for key in (
        "imap_host",
        "smtp_host",
        "smtp_port",
        "oauth_client_id",
        "oauth_authority",
    ):
        if cfg.get(key):
            profile[key] = cfg[key]
    if cfg.get("oauth_scopes"):
        profile["oauth_scopes"] = list(cfg["oauth_scopes"])
    profile = apply_env_overrides(profile, dict(os.environ))
    return name, profile


def _refresh_microsoft(tok: dict, profile: dict, account: str) -> dict:
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
    res["user"] = tok.get("user") or account_user(account)
    return res


def _refresh_google(tok: dict, profile: dict, account: str) -> dict:
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
    res["user"] = tok.get("user") or account_user(account)
    return res


def get_access_token(account: str | None = None) -> str:
    """Return a fresh OAuth2 access token for the given account.

    Only meaningful for OAuth providers (microsoft-personal, gmail).
    For app-password providers, callers should use :func:`get_app_password`.
    """
    acc = resolve_account(account)
    name, profile = account_profile(acc)
    strategy = profile["auth_strategy"]
    tok = load_token(acc)
    if tok is None:
        sys.exit(
            f"no token for account {acc!r}; run "
            f"'email-client auth add --account {acc}' first"
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
        new = _refresh_microsoft(tok, profile, acc)
    elif strategy == "loopback-oauth":
        new = _refresh_google(tok, profile, acc)
    else:
        sys.exit(f"unsupported auth strategy {strategy!r}")
    save_token(acc, new)
    return new["access_token"]


def get_app_password(account: str | None = None) -> str:
    acc = resolve_account(account)
    tok = load_token(acc)
    if tok is None:
        sys.exit(
            f"no credential for account {acc!r}; run "
            f"'email-client auth add --account {acc}' first"
        )
    pw = tok.get("app_password")
    if not pw:
        sys.exit(f"no app_password in token for {acc!r}; re-run auth for this account")
    return pw


def connect(account: str | None = None) -> imaplib.IMAP4_SSL:
    acc = resolve_account(account)
    user = account_user(acc)
    name, profile = account_profile(acc)
    host = profile["imap_host"]
    port = int(profile.get("imap_port", 993))
    if not host:
        sys.exit(
            f"provider {name} (account {acc!r}) has no IMAP host configured; "
            "set imap_host in the per-account config.json or EMAIL_CLIENT_HOST"
        )
    M = imaplib.IMAP4_SSL(host, port)
    if profile["auth_strategy"] == "app-password":
        pw = get_app_password(acc)
        M.login(user, pw)
    else:
        access = get_access_token(acc)
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


def cmd_folders(args):
    M = connect(getattr(args, "account", None))
    typ, folders = M.list()
    for f in folders:
        print(f.decode(errors="replace"))
    M.logout()


def cmd_list(args):
    M = connect(getattr(args, "account", None))
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
    M = connect(getattr(args, "account", None))
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
    M = connect(getattr(args, "account", None))
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


# -- mark / move / archive / delete --------------------------------


def _normalize_uids(spec: str) -> str:
    """Return a comma-separated UID set; accepts ``12``, ``12,15,18`` or ``12, 15``."""
    parts = [p.strip() for p in (spec or "").split(",") if p.strip()]
    if not parts:
        sys.exit("--uid is required and must contain at least one UID")
    for p in parts:
        if not p.isdigit():
            sys.exit(f"invalid UID {p!r}; expected integers separated by commas")
    return ",".join(parts)


def _server_capabilities(M: imaplib.IMAP4_SSL) -> set[str]:
    """Return the IMAP server capability set (uppercased) for the live connection."""
    typ, data = M.capability()
    if typ != "OK" or not data:
        return set()
    raw = b" ".join(d for d in data if isinstance(d, (bytes, bytearray))).decode(
        errors="replace"
    )
    return {tok.upper() for tok in raw.split()}


def cmd_mark(args):
    M = connect(getattr(args, "account", None))
    try:
        typ, _ = M.select(f'"{args.folder}"')
        if typ != "OK":
            sys.exit(f"select {args.folder!r} failed")
        uids = _normalize_uids(args.uid)
        actions: list[tuple[str, str]] = []
        if args.read:
            actions.append(("+FLAGS", r"(\Seen)"))
        if args.unread:
            actions.append(("-FLAGS", r"(\Seen)"))
        if args.flagged:
            actions.append(("+FLAGS", r"(\Flagged)"))
        if args.unflagged:
            actions.append(("-FLAGS", r"(\Flagged)"))
        if not actions:
            sys.exit(
                "pick at least one of --read / --unread / --flagged / --unflagged"
            )
        for op, flag in actions:
            typ, resp = M.uid("STORE", uids, op, flag)
            if typ != "OK":
                sys.exit(f"STORE {op} {flag} failed: {resp!r}")
        print(json.dumps({"ok": True, "uids": uids.split(","), "actions": actions}))
    finally:
        try:
            M.logout()
        except Exception:
            pass


def _move_uids(
    M: imaplib.IMAP4_SSL, uids: str, src: str, dst: str
) -> None:
    """Move the given UIDs from src to dst, using MOVE if available else COPY+EXPUNGE."""
    caps = _server_capabilities(M)
    if "MOVE" in caps:
        typ, resp = M.uid("MOVE", uids, f'"{dst}"')
        if typ != "OK":
            sys.exit(f"MOVE failed: {resp!r}")
        return
    typ, resp = M.uid("COPY", uids, f'"{dst}"')
    if typ != "OK":
        sys.exit(f"COPY failed: {resp!r}")
    typ, resp = M.uid("STORE", uids, "+FLAGS", r"(\Deleted)")
    if typ != "OK":
        sys.exit(f"STORE +Deleted failed: {resp!r}")
    typ, resp = M.expunge()
    if typ != "OK":
        sys.exit(f"EXPUNGE failed: {resp!r}")


def cmd_move(args):
    M = connect(getattr(args, "account", None))
    try:
        typ, _ = M.select(f'"{args.folder}"')
        if typ != "OK":
            sys.exit(f"select {args.folder!r} failed")
        uids = _normalize_uids(args.uid)
        _move_uids(M, uids, args.folder, args.to_folder)
        print(
            json.dumps(
                {
                    "ok": True,
                    "uids": uids.split(","),
                    "from": args.folder,
                    "to": args.to_folder,
                }
            )
        )
    finally:
        try:
            M.logout()
        except Exception:
            pass


def cmd_archive(args):
    args.to_folder = "Archive"
    cmd_move(args)


def cmd_delete(args):
    M = connect(getattr(args, "account", None))
    try:
        typ, _ = M.select(f'"{args.folder}"')
        if typ != "OK":
            sys.exit(f"select {args.folder!r} failed")
        uids = _normalize_uids(args.uid)
        if args.hard:
            typ, resp = M.uid("STORE", uids, "+FLAGS", r"(\Deleted)")
            if typ != "OK":
                sys.exit(f"STORE +Deleted failed: {resp!r}")
            typ, resp = M.expunge()
            if typ != "OK":
                sys.exit(f"EXPUNGE failed: {resp!r}")
            print(json.dumps({"ok": True, "uids": uids.split(","), "hard": True}))
        else:
            _move_uids(M, uids, args.folder, "Deleted")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "uids": uids.split(","),
                        "from": args.folder,
                        "to": "Deleted",
                    }
                )
            )
    finally:
        try:
            M.logout()
        except Exception:
            pass


# -- auth subcommands (multi-account management) -------------------


def cmd_auth_list(args):
    """Print registered accounts with public metadata only (no secrets)."""
    idx = load_accounts_index()
    accs = idx.get("accounts") or []
    out = []
    for a in accs:
        cfg = load_config(a)
        tok = load_token(a)
        provider = cfg.get("provider") or (tok.get("provider") if tok else None)
        user = cfg.get("user") or (tok.get("user") if tok else None)
        out.append(
            {
                "account": a,
                "user": user,
                "provider": provider,
                "default": a == idx.get("default"),
                "has_token": tok is not None,
            }
        )
    print(json.dumps(out, indent=2))


def cmd_auth_remove(args):
    name = args.account
    if name not in list_accounts():
        sys.exit(f"no such account {name!r}")
    import shutil

    shutil.rmtree(account_dir(name), ignore_errors=True)
    idx = load_accounts_index()
    idx["accounts"] = [a for a in idx.get("accounts") or [] if a != name]
    if idx.get("default") == name:
        idx["default"] = idx["accounts"][0] if idx["accounts"] else None
    save_accounts_index(idx)
    print(f"removed account {name}")


def main():
    ap = argparse.ArgumentParser(prog="email-client")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _add_account_arg(p):
        p.add_argument(
            "--account",
            default=None,
            help="account name (defaults to accounts.json default)",
        )

    p = sub.add_parser("list-folders")
    _add_account_arg(p)

    p = sub.add_parser("list")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--limit", type=int, default=20)
    _add_account_arg(p)

    p = sub.add_parser("get")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--uid", required=True)
    p.add_argument("--body-chars", type=int, default=4000)
    _add_account_arg(p)

    p = sub.add_parser("search")
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--query", required=True)
    p.add_argument("--limit", type=int, default=20)
    _add_account_arg(p)

    p = sub.add_parser(
        "mark",
        help="set/clear \\Seen or \\Flagged on one or more UIDs",
    )
    p.add_argument("--folder", default="INBOX")
    p.add_argument(
        "--uid",
        required=True,
        help="single UID or comma-separated UIDs (e.g. 12,15,18)",
    )
    p.add_argument("--read", action="store_true", help="set \\Seen")
    p.add_argument("--unread", action="store_true", help="clear \\Seen")
    p.add_argument("--flagged", action="store_true", help="set \\Flagged")
    p.add_argument("--unflagged", action="store_true", help="clear \\Flagged")
    _add_account_arg(p)

    p = sub.add_parser(
        "move",
        help="move one or more UIDs to another folder (MOVE if supported, "
        "else COPY+STORE+EXPUNGE)",
    )
    p.add_argument("--folder", default="INBOX", help="source folder")
    p.add_argument("--uid", required=True, help="UID or comma-separated UIDs")
    p.add_argument(
        "--to-folder",
        required=True,
        help="destination folder (e.g. Archive, Deleted, custom)",
    )
    _add_account_arg(p)

    p = sub.add_parser(
        "archive", help="convenience for move --to-folder Archive"
    )
    p.add_argument("--folder", default="INBOX", help="source folder")
    p.add_argument("--uid", required=True, help="UID or comma-separated UIDs")
    _add_account_arg(p)

    p = sub.add_parser(
        "delete",
        help="soft-delete to Deleted folder; pass --hard to expunge in place",
    )
    p.add_argument("--folder", default="INBOX", help="source folder")
    p.add_argument("--uid", required=True, help="UID or comma-separated UIDs")
    p.add_argument(
        "--hard",
        action="store_true",
        help="permanently expunge instead of moving to Deleted",
    )
    _add_account_arg(p)

    pa = sub.add_parser("auth", help="account management")
    asub = pa.add_subparsers(dest="auth_cmd", required=True)
    pa_add = asub.add_parser("add", help="register a new account")
    pa_add.add_argument("--account", required=True)
    pa_add.add_argument("--user", default=None)
    pa_add.add_argument("--provider", default=None)
    pa_add.add_argument("--reauth", action="store_true")
    asub.add_parser("list", help="show registered accounts")
    pa_rm = asub.add_parser("remove", help="delete an account dir")
    pa_rm.add_argument("--account", required=True)

    args = ap.parse_args()

    if args.cmd == "auth":
        if args.auth_cmd == "add":
            import auth as _auth_mod

            _auth_mod.run_add(
                account=args.account,
                user=args.user,
                provider=args.provider,
                reauth=args.reauth,
            )
            return
        if args.auth_cmd == "list":
            cmd_auth_list(args)
            return
        if args.auth_cmd == "remove":
            cmd_auth_remove(args)
            return

    {
        "list-folders": cmd_folders,
        "list": cmd_list,
        "get": cmd_get,
        "search": cmd_search,
        "mark": cmd_mark,
        "move": cmd_move,
        "archive": cmd_archive,
        "delete": cmd_delete,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
