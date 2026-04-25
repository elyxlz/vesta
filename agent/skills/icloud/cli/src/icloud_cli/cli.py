"""iCloud Photos CLI for vesta. Wraps pyicloud for shared album access.

Commands:
  icloud auth login [--apple-id EMAIL] [--phone-suffix DIGITS]
                                        start SMS 2FA login (background worker)
  icloud auth verify --code CODE        submit the 6-digit SMS code
  icloud auth status                    show trust / cookie state
  icloud albums [--shared|--owned]      list albums
  icloud download ALBUM --to PATH       download all photos from an album
  icloud sync-shared --to PATH          download every shared album as a subfolder

Credential resolution order:
  1. --apple-id flag (password still comes from creds file or Keeper)
  2. ICLOUD_APPLE_ID env var
  3. ~/.icloud/credentials.json   ({"account": "...", "password": "..."})
  4. Keeper record whose title matches "Apple ID" or "iCloud" (login + password fields)

Auth state lives in ~/.icloud/:
  config.json           {account, last_phone_id, phone_suffix}
  cookies/              pyicloud cookie + session jar
  state.json            current login status (phase, phone_id, pid, message)
  code.txt              written by `auth verify` and read by the bg login worker
  worker.log            stdout/stderr of the background login worker
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

ICLOUD_DIR = Path.home() / ".icloud"
COOKIE_DIR = ICLOUD_DIR / "cookies"
CONFIG_FILE = ICLOUD_DIR / "config.json"
CREDS_FILE = ICLOUD_DIR / "credentials.json"
STATE_FILE = ICLOUD_DIR / "state.json"
CODE_FILE = ICLOUD_DIR / "code.txt"
WORKER_LOG = ICLOUD_DIR / "worker.log"

# Keeper records matching any of these titles (case-insensitive substring) are
# treated as candidate Apple ID credentials. Generic so anyone can use it.
KEEPER_TITLE_HINTS = ("apple id", "icloud")
POLL_TIMEOUT_S = 20 * 60
POLL_EVERY_S = 3


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #


def _ensure_dirs() -> None:
    ICLOUD_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _write_state(**kwargs: Any) -> None:
    _ensure_dirs()
    state = _load_state()
    state.update(kwargs)
    state["updated_at"] = int(time.time())
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))


def _load_config() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def _write_config(**kwargs: Any) -> None:
    _ensure_dirs()
    cfg = _load_config()
    cfg.update(kwargs)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    CONFIG_FILE.chmod(0o600)


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #


def _load_creds_from_file() -> dict[str, str] | None:
    if not CREDS_FILE.exists():
        return None
    try:
        data = json.loads(CREDS_FILE.read_text())
        if data.get("account") and data.get("password"):
            return {"account": data["account"], "password": data["password"]}
    except Exception:
        pass
    return None


def _load_creds_from_keeper() -> dict[str, str] | None:
    """Search Keeper for a record whose title matches an Apple ID hint.

    Tries `keeper search <hint>` then fetches the first matching record's
    login + password fields. Returns None if Keeper isn't installed/configured
    or no matching record is found.
    """
    try:
        for hint in KEEPER_TITLE_HINTS:
            result = subprocess.run(
                ["keeper", f"search {hint} --format json"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0 or not result.stdout.strip():
                continue
            try:
                rows = json.loads(result.stdout)
            except json.JSONDecodeError:
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                title = str(row.get("title") or "").lower()
                if hint not in title:
                    continue
                uid = row.get("uid") or row.get("record_uid")
                if not uid:
                    continue
                got = subprocess.run(
                    ["keeper", f"get {uid} --format json --unmask"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if got.returncode != 0:
                    continue
                try:
                    data = json.loads(got.stdout)
                except json.JSONDecodeError:
                    continue
                login = data.get("login")
                password = data.get("password")
                if isinstance(login, str) and isinstance(password, str) and login and password:
                    return {"account": login, "password": password}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    return None


def _resolve_credentials(account_override: str | None = None) -> dict[str, str]:
    creds = _load_creds_from_file() or _load_creds_from_keeper()

    # Allow account-only override via flag or env, password still must come
    # from creds file / Keeper.
    env_account = os.environ.get("ICLOUD_APPLE_ID")
    explicit_account = account_override or env_account

    if not creds:
        if explicit_account:
            print(
                "Error: Apple ID specified but no password source available.\n"
                f"  Create {CREDS_FILE} with "
                "{\"account\": \"<email>\", \"password\": \"<password>\"}\n"
                "  or add an 'Apple ID' / 'iCloud' record to Keeper.",
                file=sys.stderr,
            )
        else:
            print(
                "Error: no Apple ID credentials available. Either:\n"
                f"  1. Create {CREDS_FILE} with "
                "{\"account\": \"<email>\", \"password\": \"<password>\"}, or\n"
                "  2. Add a Keeper record titled 'Apple ID' or 'iCloud' "
                "(login + password fields), or\n"
                "  3. Pass --apple-id and store the password in one of the above.",
                file=sys.stderr,
            )
        sys.exit(1)
    if explicit_account:
        creds["account"] = explicit_account
    return creds


# --------------------------------------------------------------------------- #
# Auth: login worker (foreground or background)
# --------------------------------------------------------------------------- #


def _collect_phones(auth_data: dict) -> list[dict]:
    out: list[dict] = []
    tpn = auth_data.get("trustedPhoneNumber")
    if isinstance(tpn, dict):
        out.append({"source": "trustedPhoneNumber", **tpn})
    pnv = auth_data.get("phoneNumberVerification") or {}
    if isinstance(pnv, dict):
        inner = pnv.get("trustedPhoneNumber")
        if isinstance(inner, dict):
            out.append({"source": "pnv.trustedPhoneNumber", **inner})
        for entry in pnv.get("trustedPhoneNumbers") or []:
            if isinstance(entry, dict):
                out.append({"source": "pnv.trustedPhoneNumbers", **entry})
    for entry in auth_data.get("trustedPhoneNumbers") or []:
        if isinstance(entry, dict):
            out.append({"source": "trustedPhoneNumbers", **entry})
    return out


def _pick_phone_id(candidates: list[dict], suffix: str | None = None) -> int | None:
    """Pick a trusted phone number id from Apple's auth_data.

    If `suffix` is provided, prefer numbers whose last digits match. Otherwise
    return the first candidate with an integer id (which is what Apple returns
    when the account has only one trusted phone, the common case).
    """

    def tail_digits(s: str, n: int) -> str:
        return "".join(ch for ch in s if ch.isdigit())[-n:]

    if suffix:
        s = "".join(ch for ch in suffix if ch.isdigit())
        target_last_two = s[-2:]

        # Best: exact lastTwoDigits match
        for c in candidates:
            if str(c.get("lastTwoDigits") or "") == target_last_two:
                if isinstance(c.get("id"), int):
                    return c["id"]
        # Tail of any number field, matching the full suffix when available
        for c in candidates:
            for key in ("numberWithDialCode", "number", "obfuscatedNumber"):
                v = c.get(key)
                if isinstance(v, str):
                    if tail_digits(v, len(s)) == s or tail_digits(v, 2) == target_last_two:
                        if isinstance(c.get("id"), int):
                            return c["id"]

    # No suffix, or suffix didn't match: take the first candidate that has an id.
    for c in candidates:
        if isinstance(c.get("id"), int):
            return c["id"]
    return None


def _run_login_worker(account: str, password: str, phone_suffix: str | None = None) -> int:
    """Long-running worker. Authenticates, triggers SMS, polls CODE_FILE,
    submits code, trusts session, persists cookies."""
    from pyicloud import PyiCloudService
    from pyicloud.base import CONTENT_TYPE_JSON, CONTENT_TYPE_TEXT

    _ensure_dirs()
    _write_state(phase="connecting", account=account, pid=os.getpid())

    api = PyiCloudService(account, password, cookie_directory=str(COOKIE_DIR))

    if not api.requires_2fa and api.is_trusted_session:
        _write_state(phase="trusted", message="already trusted; no 2FA needed")
        return 0

    # Merge JSON-shell auth_data to find trusted phones
    html_auth = dict(api._auth_data or {})
    candidates = _collect_phones(html_auth)
    if not candidates:
        try:
            headers = api._get_auth_headers({"Accept": CONTENT_TYPE_JSON})
            resp = api.session.get(api._auth_endpoint, headers=headers)
            json_auth = resp.json() if resp.status_code < 400 else {}
        except Exception as e:
            json_auth = {}
            _write_state(message=f"json shell fetch err: {type(e).__name__}:{e}")
        merged = dict(html_auth)
        merged.update(json_auth or {})
        api._auth_data = merged
        candidates = _collect_phones(merged)

    phone_id = _pick_phone_id(candidates, suffix=phone_suffix)
    if phone_id is None:
        msg = (
            f"no trusted phone matched suffix {phone_suffix}"
            if phone_suffix
            else "no trusted phone numbers returned by Apple"
        )
        _write_state(
            phase="error",
            message=msg,
            candidates=candidates,
        )
        return 2

    cfg_update: dict[str, Any] = {"account": account, "last_phone_id": phone_id}
    if phone_suffix:
        cfg_update["phone_suffix"] = phone_suffix
    _write_config(**cfg_update)
    _write_state(phase="sending_sms", phone_id=phone_id)

    headers = api._get_auth_headers({"Accept": CONTENT_TYPE_JSON})
    sms_url = f"{api._auth_endpoint}/verify/phone"
    sms_body = {"phoneNumber": {"id": phone_id}, "mode": "sms"}
    resp = api.session.put(sms_url, json=sms_body, headers=headers)
    if resp.status_code >= 400:
        _write_state(
            phase="error",
            message=f"SMS trigger failed: {resp.status_code} {resp.text[:300]!r}",
        )
        return 3

    _write_state(
        phase="awaiting_code",
        message=f"SMS sent to phone id {phone_id}; run `icloud auth verify --code <code>`",
    )

    if CODE_FILE.exists():
        try:
            CODE_FILE.unlink()
        except Exception:
            pass

    deadline = time.time() + POLL_TIMEOUT_S
    code: str | None = None
    while time.time() < deadline:
        if CODE_FILE.exists():
            raw = CODE_FILE.read_text().strip()
            digits = "".join(ch for ch in raw if ch.isdigit())
            if len(digits) == 6:
                code = digits
                break
        time.sleep(POLL_EVERY_S)

    if code is None:
        _write_state(phase="error", message="timed out waiting for code")
        return 4

    _write_state(phase="submitting_code")

    submit_headers = api._get_auth_headers(
        {"Accept": f"{CONTENT_TYPE_JSON}, {CONTENT_TYPE_TEXT}"}
    )
    submit_url = f"{api._auth_endpoint}/verify/phone/securitycode"
    submit_body = {
        "phoneNumber": {"id": phone_id},
        "securityCode": {"code": code},
        "mode": "sms",
    }
    resp = api.session.post(submit_url, json=submit_body, headers=submit_headers)
    if resp.status_code >= 400:
        _write_state(
            phase="error",
            message=f"code rejected: {resp.status_code} {resp.text[:300]!r}",
        )
        try:
            CODE_FILE.unlink()
        except Exception:
            pass
        return 5

    try:
        api.trust_session()
    except Exception as e:
        _write_state(message=f"trust_session warning: {type(e).__name__}:{e}")

    try:
        CODE_FILE.unlink()
    except Exception:
        pass

    _write_state(
        phase="trusted",
        message="session trusted; cookies saved",
        is_trusted_session=bool(api.is_trusted_session),
    )
    return 0


def cmd_auth_login(args: argparse.Namespace) -> None:
    creds = _resolve_credentials(args.apple_id)
    _ensure_dirs()

    # Phone suffix: explicit flag wins, then last-used config, else None
    # (which means "first / only trusted phone").
    phone_suffix: str | None = args.phone_suffix or _load_config().get("phone_suffix")

    # If we're already trusted, short-circuit.
    try:
        from pyicloud import PyiCloudService

        api = PyiCloudService(creds["account"], cookie_directory=str(COOKIE_DIR))
        if api.is_trusted_session:
            _write_state(phase="trusted", account=creds["account"], message="already trusted")
            print(json.dumps({"status": "already_trusted", "account": creds["account"]}, indent=2))
            return
    except Exception:
        pass

    if args.foreground:
        rc = _run_login_worker(creds["account"], creds["password"], phone_suffix=phone_suffix)
        sys.exit(rc)

    # Background spawn: re-exec ourselves with --worker.
    log_fh = open(WORKER_LOG, "ab", buffering=0)
    env = os.environ.copy()
    env["ICLOUD_WORKER_ACCOUNT"] = creds["account"]
    env["ICLOUD_WORKER_PASSWORD"] = creds["password"]
    if phone_suffix:
        env["ICLOUD_WORKER_PHONE_SUFFIX"] = phone_suffix
    proc = subprocess.Popen(
        [sys.executable, "-m", "icloud_cli.cli", "_worker"],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    _write_state(phase="starting", account=creds["account"], pid=proc.pid)

    # Wait briefly for the worker to advance to "awaiting_code" or fail.
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(1)
        state = _load_state()
        phase = state.get("phase")
        if phase in ("awaiting_code", "trusted", "error"):
            break

    state = _load_state()
    print(json.dumps(state, indent=2, default=str))
    if state.get("phase") == "error":
        sys.exit(1)
    if state.get("phase") == "awaiting_code":
        print(
            "\nNext: ask the user for the 6-digit SMS code, then run:\n"
            "  icloud auth verify --code <code>",
            file=sys.stderr,
        )


def cmd_auth_verify(args: argparse.Namespace) -> None:
    _ensure_dirs()
    digits = "".join(ch for ch in args.code if ch.isdigit())
    if len(digits) != 6:
        print(f"Error: code must be 6 digits, got {args.code!r}", file=sys.stderr)
        sys.exit(1)
    state = _load_state()
    if state.get("phase") not in ("awaiting_code", "submitting_code"):
        print(
            f"Warning: state phase is {state.get('phase')!r}; expected 'awaiting_code'. "
            "Writing code anyway.",
            file=sys.stderr,
        )
    CODE_FILE.write_text(digits)
    CODE_FILE.chmod(0o600)

    # Wait for worker to consume the code and reach trusted/error
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(2)
        state = _load_state()
        if state.get("phase") in ("trusted", "error"):
            break

    state = _load_state()
    print(json.dumps(state, indent=2, default=str))
    if state.get("phase") != "trusted":
        sys.exit(1)


def cmd_auth_status(args: argparse.Namespace) -> None:
    state = _load_state()
    cfg = _load_config()
    account = cfg.get("account") or state.get("account")

    info: dict[str, Any] = {
        "account": account,
        "cookies_dir": str(COOKIE_DIR),
        "cookies_exist": COOKIE_DIR.exists() and any(COOKIE_DIR.iterdir()),
        "phase": state.get("phase"),
        "message": state.get("message"),
    }

    if account and info["cookies_exist"]:
        try:
            from pyicloud import PyiCloudService

            api = PyiCloudService(account, cookie_directory=str(COOKIE_DIR))
            info["is_trusted_session"] = bool(api.is_trusted_session)
            info["requires_2fa"] = bool(api.requires_2fa)
        except Exception as e:
            info["session_error"] = f"{type(e).__name__}:{e}"

    print(json.dumps(info, indent=2, default=str))
    if not info.get("is_trusted_session"):
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Albums + photos
# --------------------------------------------------------------------------- #


def _connect() -> Any:
    cfg = _load_config()
    account = (
        os.environ.get("ICLOUD_APPLE_ID")
        or cfg.get("account")
        or _load_state().get("account")
    )
    if not account:
        creds = _load_creds_from_file() or _load_creds_from_keeper()
        if creds:
            account = creds["account"]
    if not account:
        print("Error: unknown account. Run `icloud auth login` first.", file=sys.stderr)
        sys.exit(1)

    from pyicloud import PyiCloudService

    api = PyiCloudService(account, cookie_directory=str(COOKIE_DIR))
    if not api.is_trusted_session:
        print(
            "Error: session not trusted. Run `icloud auth login` then `icloud auth verify --code <code>`.",
            file=sys.stderr,
        )
        sys.exit(2)
    return api


def _serialize_shared(album: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": getattr(album, "name", None),
        "id": getattr(album, "id", None),
        "kind": "shared",
        "sharing_type": getattr(album, "sharing_type", None),
    }
    try:
        entry["photo_count"] = len(album)
    except Exception as e:
        entry["photo_count_error"] = f"{type(e).__name__}:{e}"
    return entry


def _serialize_owned(album: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": getattr(album, "name", None) or getattr(album, "title", None),
        "id": getattr(album, "id", None),
        "kind": "owned",
    }
    try:
        entry["photo_count"] = len(album)
    except Exception as e:
        entry["photo_count_error"] = f"{type(e).__name__}:{e}"
    return entry


def cmd_albums(args: argparse.Namespace) -> None:
    api = _connect()
    out: dict[str, Any] = {"shared": [], "owned": [], "errors": {}}
    if not args.owned:
        try:
            for album in api.photos.shared_streams:
                out["shared"].append(_serialize_shared(album))
        except Exception as e:
            out["errors"]["shared"] = f"{type(e).__name__}:{e}"
    if not args.shared:
        try:
            for album in api.photos.albums:
                out["owned"].append(_serialize_owned(album))
        except Exception as e:
            out["errors"]["owned"] = f"{type(e).__name__}:{e}"
    print(json.dumps(out, indent=2, default=str))


def _find_album(api: Any, key: str) -> Any:
    """Find an album in shared_streams or owned albums by id or name."""
    try:
        for album in api.photos.shared_streams:
            if album.id == key or album.name == key:
                return album
    except Exception:
        pass
    try:
        for album in api.photos.albums:
            aname = getattr(album, "name", None) or getattr(album, "title", None)
            if album.id == key or aname == key:
                return album
    except Exception:
        pass
    return None


def _human_size(n: int | None) -> str:
    if n is None:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f}TB"


def _safe_filename(name: str) -> str:
    bad = '/\x00'
    return "".join("_" if c in bad else c for c in name)


def _download_one(
    api: Any,
    photo: Any,
    dest_dir: Path,
    quality: str,
    include_videos: bool,
) -> tuple[bool, str]:
    """Download a single asset. Returns (downloaded, message)."""
    try:
        item_type = photo.item_type
    except Exception:
        item_type = "image"
    if item_type == "movie" and not include_videos:
        return False, "skipped (video)"

    versions = photo.versions
    if not versions:
        return False, "no versions"

    # Quality preference
    pref_order = {
        "original": ["original", "medium", "thumb"],
        "medium": ["medium", "original", "thumb"],
        "small": ["thumb", "medium", "original"],
    }[quality]
    chosen_key = None
    for key in pref_order:
        if key in versions and versions[key].get("url"):
            chosen_key = key
            break
    if chosen_key is None:
        return False, "no version URL"

    version = versions[chosen_key]
    url = version["url"]
    fname = version.get("filename") or photo.filename or f"{photo.id}"
    fname = _safe_filename(fname)
    dest = dest_dir / fname
    if dest.exists():
        local_size = dest.stat().st_size
        expected = version.get("size") or 0
        # Shared streams report size=0; treat any non-empty existing file as "done".
        if local_size > 0 and (expected == 0 or local_size == expected):
            return False, "exists"

    # Stream download
    resp = api.session.get(url, stream=True)
    if resp.status_code >= 400:
        return False, f"http {resp.status_code}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            if chunk:
                f.write(chunk)
    tmp.rename(dest)
    return True, _human_size(version.get("size"))


def cmd_download(args: argparse.Namespace) -> None:
    api = _connect()
    album = _find_album(api, args.album)
    if album is None:
        print(f"Error: album not found: {args.album!r}", file=sys.stderr)
        sys.exit(1)

    dest = Path(args.to).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    name = getattr(album, "name", "?")
    try:
        total = len(album)
    except Exception:
        total = None

    print(
        f"Downloading album {name!r} (id={album.id}, count={total}) "
        f"to {dest} [quality={args.quality}, videos={args.include_videos}]",
        file=sys.stderr,
    )

    downloaded = 0
    skipped = 0
    failed: list[str] = []
    started = time.time()
    for i, photo in enumerate(album, start=1):
        try:
            ok, msg = _download_one(api, photo, dest, args.quality, args.include_videos)
        except Exception as e:
            ok, msg = False, f"err {type(e).__name__}:{e}"
        if ok:
            downloaded += 1
        else:
            if msg.startswith("err"):
                failed.append(f"{photo.filename}: {msg}")
            else:
                skipped += 1
        if i % 10 == 0 or i == total:
            elapsed = time.time() - started
            rate = i / elapsed if elapsed else 0
            print(
                f"  [{i}/{total or '?'}] downloaded={downloaded} skipped={skipped} "
                f"failed={len(failed)} ({rate:.1f}/s)",
                file=sys.stderr,
            )

    summary = {
        "album": name,
        "id": album.id,
        "dest": str(dest),
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": len(failed),
        "errors": failed[:20],
        "elapsed_seconds": round(time.time() - started, 1),
    }
    print(json.dumps(summary, indent=2, default=str))


def cmd_sync_shared(args: argparse.Namespace) -> None:
    api = _connect()
    root = Path(args.to).expanduser()
    root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for album in api.photos.shared_streams:
        name = getattr(album, "name", album.id)
        sub = root / _safe_filename(name)
        sub.mkdir(parents=True, exist_ok=True)
        try:
            total = len(album)
        except Exception:
            total = None
        print(f"-- {name} ({total} items) -> {sub}", file=sys.stderr)
        downloaded = 0
        skipped = 0
        failed = 0
        for i, photo in enumerate(album, start=1):
            try:
                ok, msg = _download_one(api, photo, sub, args.quality, args.include_videos)
            except Exception as e:
                ok, msg = False, f"err {type(e).__name__}:{e}"
            if ok:
                downloaded += 1
            elif msg.startswith("err"):
                failed += 1
            else:
                skipped += 1
            if i % 25 == 0:
                print(
                    f"   [{i}/{total or '?'}] downloaded={downloaded} skipped={skipped} failed={failed}",
                    file=sys.stderr,
                )
        results.append(
            {
                "album": name,
                "id": album.id,
                "dest": str(sub),
                "downloaded": downloaded,
                "skipped": skipped,
                "failed": failed,
            }
        )
    print(json.dumps({"root": str(root), "albums": results}, indent=2, default=str))


# --------------------------------------------------------------------------- #
# Argparse
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="icloud", description="iCloud Photos CLI")
    sub = p.add_subparsers(dest="command", required=True)

    auth = sub.add_parser("auth", help="Auth: login, verify, status")
    auth_sub = auth.add_subparsers(dest="auth_cmd", required=True)

    a_login = auth_sub.add_parser("login", help="Start SMS 2FA login flow")
    a_login.add_argument(
        "--apple-id",
        dest="apple_id",
        default=None,
        help="Apple ID email (else: $ICLOUD_APPLE_ID, ~/.icloud/credentials.json, Keeper)",
    )
    a_login.add_argument(
        "--phone-suffix",
        dest="phone_suffix",
        default=None,
        help="Last digits of the trusted phone to receive SMS on; "
        "default: first/only trusted phone returned by Apple",
    )
    a_login.add_argument(
        "--foreground",
        action="store_true",
        help="Run the login worker in the foreground instead of forking",
    )

    a_verify = auth_sub.add_parser("verify", help="Submit the 6-digit SMS code")
    a_verify.add_argument("--code", required=True)

    auth_sub.add_parser("status", help="Show trust status")

    al = sub.add_parser("albums", help="List albums")
    grp = al.add_mutually_exclusive_group()
    grp.add_argument("--shared", action="store_true", help="Only shared streams")
    grp.add_argument("--owned", action="store_true", help="Only owned albums")

    dl = sub.add_parser("download", help="Download all photos from an album")
    dl.add_argument("album", help="Album id or name")
    dl.add_argument("--to", required=True, help="Destination directory")
    dl.add_argument(
        "--include-videos",
        dest="include_videos",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include videos (default: yes)",
    )
    dl.add_argument(
        "--quality",
        choices=["original", "medium", "small"],
        default="original",
    )

    ss = sub.add_parser("sync-shared", help="Download every shared album to subfolders")
    ss.add_argument("--to", required=True)
    ss.add_argument(
        "--include-videos",
        dest="include_videos",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    ss.add_argument("--quality", choices=["original", "medium", "small"], default="original")

    # internal
    sub.add_parser("_worker", help=argparse.SUPPRESS)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "_worker":
        account = os.environ.get("ICLOUD_WORKER_ACCOUNT")
        password = os.environ.get("ICLOUD_WORKER_PASSWORD")
        phone_suffix = os.environ.get("ICLOUD_WORKER_PHONE_SUFFIX") or None
        if not account or not password:
            print("worker: missing ICLOUD_WORKER_ACCOUNT/PASSWORD env", file=sys.stderr)
            sys.exit(1)
        try:
            rc = _run_login_worker(account, password, phone_suffix=phone_suffix)
        except Exception as e:
            tb = traceback.format_exc()
            _write_state(phase="error", message=f"worker crashed: {type(e).__name__}:{e}", traceback=tb)
            print(tb, file=sys.stderr)
            sys.exit(1)
        sys.exit(rc)

    if args.command == "auth":
        if args.auth_cmd == "login":
            cmd_auth_login(args)
        elif args.auth_cmd == "verify":
            cmd_auth_verify(args)
        elif args.auth_cmd == "status":
            cmd_auth_status(args)
        return

    if args.command == "albums":
        cmd_albums(args)
    elif args.command == "download":
        cmd_download(args)
    elif args.command == "sync-shared":
        cmd_sync_shared(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
