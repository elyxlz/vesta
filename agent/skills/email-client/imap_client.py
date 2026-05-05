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

For one release the legacy ``IMAP_MAIL_*`` names are still honored with
a stderr deprecation warning. The legacy state dir ``~/.imap-mail`` is
auto-migrated to ``~/.email-client/accounts/default/`` on first run.

Backwards compatibility: a token file written by the v0.1 release
(no ``provider`` key) is treated as ``microsoft-personal``. A
single-account token at ``$EMAIL_CLIENT_DIR/token.json`` is migrated
into ``$EMAIL_CLIENT_DIR/accounts/default/`` on first run.
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
    apply_env_overrides,
    detect_provider,
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
    """Read an env var, with legacy IMAP_MAIL_* fallback for new EMAIL_CLIENT_* names."""
    val = os.environ.get(name)
    if not val and name.startswith("EMAIL_CLIENT_"):
        legacy = "IMAP_MAIL_" + name[len("EMAIL_CLIENT_") :]
        val = os.environ.get(legacy)
        if val:
            print(
                f"email-client: warning: {legacy} is deprecated, "
                f"rename to {name} in your shell rc",
                file=sys.stderr,
            )
    if not val:
        val = default
    if required and not val:
        sys.exit(f"missing required env var {name}")
    return val or ""


def _state_dir() -> pathlib.Path:
    """Return the top-level email-client state dir.

    Resolution order:
      1. ``$EMAIL_CLIENT_DIR``
      2. ``$IMAP_MAIL_DIR`` (legacy, with deprecation warning)
      3. ``~/.email-client``
      4. ``~/.imap-mail`` if it exists and ~/.email-client does not
         (legacy single-account install, with stderr migration hint)
    """
    explicit = os.environ.get("EMAIL_CLIENT_DIR") or os.environ.get("IMAP_MAIL_DIR")
    if explicit:
        if "IMAP_MAIL_DIR" in os.environ and "EMAIL_CLIENT_DIR" not in os.environ:
            print(
                "email-client: warning: IMAP_MAIL_DIR is deprecated, "
                "rename to EMAIL_CLIENT_DIR in your shell rc",
                file=sys.stderr,
            )
        d = pathlib.Path(explicit)
        d.mkdir(parents=True, exist_ok=True)
        return d
    new = pathlib.Path.home() / ".email-client"
    legacy = pathlib.Path.home() / ".imap-mail"
    if not new.exists() and legacy.exists():
        print(
            f"email-client: using legacy state dir {legacy}; "
            f"consider moving it to {new} (or set EMAIL_CLIENT_DIR)",
            file=sys.stderr,
        )
        return legacy
    new.mkdir(parents=True, exist_ok=True)
    return new


# -- multi-account state layout -------------------------------------


def _accounts_dir() -> pathlib.Path:
    return _state_dir() / "accounts"


def _accounts_index_path() -> pathlib.Path:
    return _state_dir() / "accounts.json"


def load_accounts_index() -> dict:
    """Return the accounts index dict.

    Triggers an auto-migration if the index is missing but a legacy
    single-account token.json exists at the state-dir root or at
    ~/.imap-mail/token.json.
    """
    p = _accounts_index_path()
    if not p.exists():
        _maybe_migrate_legacy_single_account()
    if not p.exists():
        return {"accounts": [], "default": None}
    return json.loads(p.read_text())


def save_accounts_index(idx: dict) -> None:
    p = _accounts_index_path()
    p.write_text(json.dumps(idx, indent=2))


def _maybe_migrate_legacy_single_account() -> None:
    """Migrate a single-account install to the multi-account layout.

    Looks for ``$EMAIL_CLIENT_DIR/token.json`` first, then
    ``~/.imap-mail/token.json``. If found, copies the token plus the
    high-UID watermark into ``accounts/default/`` and writes
    ``accounts.json``. Idempotent; safe to call repeatedly.
    """
    state = _state_dir()
    idx_path = state / "accounts.json"
    if idx_path.exists():
        return
    candidates = [state / "token.json"]
    legacy_root = pathlib.Path.home() / ".imap-mail"
    if legacy_root != state:
        candidates.append(legacy_root / "token.json")
    src_token = next((c for c in candidates if c.exists()), None)
    if not src_token:
        return
    dst_dir = state / "accounts" / "default"
    dst_dir.mkdir(parents=True, exist_ok=True)
    src_dir = src_token.parent
    dst_token = dst_dir / "token.json"
    dst_token.write_text(src_token.read_text())
    dst_token.chmod(0o600)
    src_high = src_dir / "high_uid.txt"
    if src_high.exists():
        (dst_dir / "high_uid.txt").write_text(src_high.read_text())
    cfg = {}
    try:
        tok = json.loads(src_token.read_text())
        if tok.get("user"):
            cfg["user"] = tok["user"]
        if tok.get("provider"):
            cfg["provider"] = tok["provider"]
    except Exception:
        pass
    (dst_dir / "config.json").write_text(json.dumps(cfg, indent=2))
    idx_path.write_text(
        json.dumps({"accounts": ["default"], "default": "default"}, indent=2)
    )
    print(
        f"email-client: migrated single-account install at {src_token} "
        f"to {dst_dir}; the legacy file is left in place for safety",
        file=sys.stderr,
    )


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
    token.json["user"] field, then the env var ``EMAIL_CLIENT_USER``
    (legacy ``IMAP_MAIL_USER``). Errors loud if none resolves.
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
      4. ``microsoft-personal`` fallback (legacy)

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


# Backwards-compat shim: the old single-account API. Redirects to the
# default account.
def current_profile() -> tuple[str, dict]:
    acc = default_account()
    if acc:
        return account_profile(acc)
    return resolve_provider(dict(os.environ))


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


def get_access_token(
    account: str | None = None, scopes: list[str] | None = None
) -> str:
    """Return a fresh OAuth2 access token for the given account.

    Only meaningful for OAuth providers (microsoft-personal, gmail).
    For app-password providers, callers should use :func:`get_app_password`.
    The ``scopes`` argument is accepted for backwards compatibility and
    ignored when the provider profile already specifies its scopes.
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


# Compatibility shim. Older callers may import _detect_provider from
# this module; keep the symbol live and forward to providers.py.
def _detect_provider(email: str) -> str | None:
    return detect_provider(email)


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
    }[args.cmd](args)


if __name__ == "__main__":
    main()
