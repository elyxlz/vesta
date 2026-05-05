#!/usr/bin/env python3
"""IMAP client over OAuth2 (XOAUTH2) or app-password basic auth.

Supports multiple providers (Microsoft personal, Gmail, Yahoo, iCloud,
Fastmail, generic IMAP) via the profile registry in ``providers.py``,
and multiple accounts simultaneously via the per-account state layout
in ``$EMAIL_CLIENT_DIR/accounts/<name>/``.

Subcommands: list-folders, list, get, search, attachments, mark, move,
archive, delete, auth.

Provider is auto-detected from the account's email domain, or pinned
via the per-account ``config.json`` (or ``--provider`` on ``auth.py``).

The IMAP layer uses ``imap_tools`` (MailBox API). OAuth refresh and
SMTP send still use stdlib (smtplib + msal/urllib).

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
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

from imap_tools import AND, MailBox, MailMessageFlags

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


def connect(account: str | None = None, *, initial_folder: str | None = "INBOX") -> MailBox:
    """Return a logged-in ``imap_tools.MailBox`` for the chosen account.

    Picks XOAUTH2 or app-password automatically based on the resolved
    provider profile. The mailbox is selected on ``initial_folder``
    (defaults to ``INBOX``); pass ``None`` to skip folder selection.
    """
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
    mb = MailBox(host, port=port)
    if profile["auth_strategy"] == "app-password":
        mb.login(user, get_app_password(acc), initial_folder=initial_folder)
    else:
        mb.xoauth2(user, get_access_token(acc), initial_folder=initial_folder)
    return mb


# -- helpers --------------------------------------------------------


def _from_full(msg) -> str:
    """Return the original ``From`` header as ``Name <email>`` (or just email)."""
    return msg.from_values.full if msg.from_values else ""


def _to_full(msg) -> str:
    """Return the joined ``To`` header values, preserving display names."""
    return ", ".join(a.full for a in msg.to_values)


def _safe_filename(name: str | None, fallback: str) -> str:
    """Sanitize a filename for safe disk write: strip path separators and nulls."""
    if not name:
        return fallback
    cleaned = name.replace("\x00", "").replace("/", "_").replace("\\", "_")
    cleaned = cleaned.lstrip(". ").strip()
    return cleaned or fallback


def _msg_summary(msg, *, include_to: bool = True) -> dict:
    """Return the JSON summary used by ``list`` / ``search`` / poll daemon.

    ``list`` includes ``to``; ``search`` historically does not.
    """
    out: dict = {"uid": msg.uid, "from": _from_full(msg)}
    if include_to:
        out["to"] = _to_full(msg)
    out["subject"] = msg.subject
    out["date"] = msg.date_str
    return out


# -- read commands --------------------------------------------------


def cmd_folders(args):
    """Print one folder per line in raw IMAP LIST shape: ``(flags) "/" Name``."""
    with connect(getattr(args, "account", None), initial_folder=None) as mb:
        for fi in mb.folder.list():
            flags = " ".join(fi.flags) if fi.flags else ""
            print(f'({flags}) "{fi.delim}" {fi.name}')


def _fetch_summaries(args, *, include_to: bool, criteria) -> None:
    with connect(getattr(args, "account", None), initial_folder=None) as mb:
        mb.folder.set(args.folder)
        # imap_tools ``limit`` keeps the FIRST N; the original CLI keeps the
        # LAST N (most recent). Use ``reverse=True`` + ``limit`` to get the
        # last N, then re-reverse so output order matches the historical
        # oldest-first layout.
        msgs = list(
            mb.fetch(
                criteria,
                limit=args.limit or None,
                reverse=True,
                mark_seen=False,
                headers_only=True,
            )
        )
        msgs.reverse()
        if not msgs:
            print("[]")
            return
        out = [_msg_summary(m, include_to=include_to) for m in msgs]
        print(json.dumps(out, indent=2, ensure_ascii=False))


def cmd_list(args):
    _fetch_summaries(args, include_to=True, criteria="ALL")


def cmd_search(args):
    _fetch_summaries(args, include_to=False, criteria=args.query)


def cmd_get(args):
    with connect(getattr(args, "account", None), initial_folder=None) as mb:
        mb.folder.set(args.folder)
        msgs = list(mb.fetch(AND(uid=args.uid), mark_seen=False, limit=1))
        if not msgs:
            sys.exit("not found")
        m = msgs[0]
        body = m.text or m.html or ""
        print(
            json.dumps(
                {
                    "from": _from_full(m),
                    "to": _to_full(m),
                    "subject": m.subject,
                    "date": m.date_str,
                    "body": body[: args.body_chars],
                },
                indent=2,
                ensure_ascii=False,
            )
        )


def cmd_attachments(args):
    """List or download attachments on a single message UID.

    Default behavior: list. With ``--download`` save all attachments
    to ``$EMAIL_CLIENT_DIR/attachments/<uid>/`` (override with
    ``--out-dir``). With ``--part`` save just one specific attachment
    (matched by ``part_index`` from the listing).
    """
    with connect(getattr(args, "account", None), initial_folder=None) as mb:
        mb.folder.set(args.folder)
        msgs = list(mb.fetch(AND(uid=args.uid), mark_seen=False, limit=1))
        if not msgs:
            sys.exit(f"uid {args.uid!r} not found in folder {args.folder!r}")
        atts = list(msgs[0].attachments)

    items: list[dict] = []
    for idx, att in enumerate(atts):
        items.append(
            {
                "part_index": idx,
                "name": _safe_filename(att.filename, f"part-{idx}.bin"),
                "content_type": att.content_type,
                "size_bytes": att.size if att.size is not None else len(att.payload),
                "payload": att.payload,
            }
        )

    if not args.download:
        listing = [{k: v for k, v in it.items() if k != "payload"} for it in items]
        print(json.dumps(listing, indent=2, ensure_ascii=False))
        return

    if args.part is not None:
        items = [it for it in items if it["part_index"] == args.part]
        if not items:
            sys.exit(
                f"no attachment with part_index={args.part} on uid={args.uid}"
            )

    if not items:
        print(json.dumps({"saved": [], "uid": args.uid}, indent=2))
        return

    if args.out_dir:
        out_dir = pathlib.Path(args.out_dir).expanduser()
    else:
        out_dir = _state_dir() / "attachments" / str(args.uid)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: list[dict] = []
    used: set[str] = set()
    for it in items:
        name = it["name"]
        # Avoid clobbering when two attachments share a filename.
        candidate = name
        n = 1
        while candidate in used or (out_dir / candidate).exists():
            stem, _, ext = name.rpartition(".")
            if ext and stem:
                candidate = f"{stem}.{n}.{ext}"
            else:
                candidate = f"{name}.{n}"
            n += 1
        used.add(candidate)
        target = out_dir / candidate
        target.write_bytes(it["payload"])
        saved.append(
            {
                "part_index": it["part_index"],
                "name": candidate,
                "content_type": it["content_type"],
                "size_bytes": it["size_bytes"],
                "path": str(target),
            }
        )
    print(json.dumps({"uid": args.uid, "saved": saved}, indent=2, ensure_ascii=False))


# -- mark / move / archive / delete --------------------------------


def _normalize_uids(spec: str) -> list[str]:
    """Return a list of UID strings; accepts ``12``, ``12,15,18`` or ``12, 15``."""
    parts = [p.strip() for p in (spec or "").split(",") if p.strip()]
    if not parts:
        sys.exit("--uid is required and must contain at least one UID")
    for p in parts:
        if not p.isdigit():
            sys.exit(f"invalid UID {p!r}; expected integers separated by commas")
    return parts


def cmd_mark(args):
    actions: list[tuple[str, bool]] = []
    if args.read:
        actions.append((MailMessageFlags.SEEN, True))
    if args.unread:
        actions.append((MailMessageFlags.SEEN, False))
    if args.flagged:
        actions.append((MailMessageFlags.FLAGGED, True))
    if args.unflagged:
        actions.append((MailMessageFlags.FLAGGED, False))
    if not actions:
        sys.exit("pick at least one of --read / --unread / --flagged / --unflagged")
    uids = _normalize_uids(args.uid)
    with connect(getattr(args, "account", None), initial_folder=None) as mb:
        mb.folder.set(args.folder)
        for flag, value in actions:
            mb.flag(uids, flag, value)
    print(
        json.dumps(
            {
                "ok": True,
                "uids": uids,
                "actions": [
                    ("+FLAGS" if v else "-FLAGS", f"({f})") for f, v in actions
                ],
            }
        )
    )


def cmd_move(args):
    uids = _normalize_uids(args.uid)
    with connect(getattr(args, "account", None), initial_folder=None) as mb:
        mb.folder.set(args.folder)
        mb.move(uids, args.to_folder)
    print(
        json.dumps(
            {
                "ok": True,
                "uids": uids,
                "from": args.folder,
                "to": args.to_folder,
            }
        )
    )


def cmd_archive(args):
    args.to_folder = "Archive"
    cmd_move(args)


def cmd_delete(args):
    uids = _normalize_uids(args.uid)
    with connect(getattr(args, "account", None), initial_folder=None) as mb:
        mb.folder.set(args.folder)
        if args.hard:
            mb.delete(uids)
            print(json.dumps({"ok": True, "uids": uids, "hard": True}))
            return
        mb.move(uids, "Deleted")
    if not args.hard:
        print(
            json.dumps(
                {
                    "ok": True,
                    "uids": uids,
                    "from": args.folder,
                    "to": "Deleted",
                }
            )
        )


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
        "attachments",
        help="list or download attachments on a single message UID",
    )
    p.add_argument("--folder", default="INBOX")
    p.add_argument("--uid", required=True)
    p.add_argument(
        "--download",
        action="store_true",
        help="save attachments to disk instead of just listing them",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help="override download directory "
        "(default $EMAIL_CLIENT_DIR/attachments/<uid>/)",
    )
    p.add_argument(
        "--part",
        type=int,
        default=None,
        help="only download a specific attachment by its part_index",
    )
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
        "attachments": cmd_attachments,
        "mark": cmd_mark,
        "move": cmd_move,
        "archive": cmd_archive,
        "delete": cmd_delete,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
