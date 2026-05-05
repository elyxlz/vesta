#!/usr/bin/env python3
"""IMAP poll daemon (multi-account).

Polls every registered account's INBOX every N seconds and writes a
notification JSON into ~/agent/notifications/ for each new message.
Auto-refreshes the OAuth token via the imap_client helper. No promo
blocklist by default; the agent decides what to surface to the user.

The daemon iterates over every account named in
``$EMAIL_CLIENT_DIR/accounts.json``. Each account has its own
high-UID watermark stored at
``$EMAIL_CLIENT_DIR/accounts/<name>/high_uid.txt``. If an account's
poll fails the loop logs the error and moves on to the next account.

Notifications are written with the source ``email-client`` and an
``account`` field naming the source mailbox. The filename includes the
account name so simultaneous notifications from multiple accounts
never collide.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import time
import uuid
from email import message_from_bytes
from email.header import decode_header

# Reuse imap_client helpers.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import (  # noqa: E402
    _env,
    account_dir,
    connect,
    list_accounts,
    load_accounts_index,
)

NOTIF_DIR = pathlib.Path.home() / "agent" / "notifications"


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


def write_notification(account: str, meta: dict) -> None:
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "email-client",
        "type": "email",
        "account": account,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "from": meta["from"],
        "to": meta.get("to", ""),
        "subject": meta["subject"],
        "date": meta["date"],
        "uid": meta["uid"],
    }
    fname = (
        f"email-client-{account}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json"
    )
    (NOTIF_DIR / fname).write_text(json.dumps(notif, ensure_ascii=False, indent=2))


def get_high_uid(path: pathlib.Path) -> int:
    if path.exists():
        return int(path.read_text().strip() or 0)
    return 0


def set_high_uid(path: pathlib.Path, n: int) -> None:
    path.write_text(str(n))


def poll_once(account: str, M, log, high_uid_path: pathlib.Path) -> None:
    M.select("INBOX", readonly=True)
    high = get_high_uid(high_uid_path)
    if high == 0:
        # First run for this account: seed with the latest UID, do not
        # flood with backlog.
        typ, data = M.uid("SEARCH", "ALL")
        ids = data[0].split()
        if ids:
            set_high_uid(high_uid_path, int(ids[-1]))
            log(f"[{account}] seeded high_uid={ids[-1].decode()}")
        return

    typ, data = M.uid("SEARCH", f"UID {high + 1}:*")
    if typ != "OK" or not data or not data[0]:
        return
    raw = data[0].split()
    new_ids = [int(x) for x in raw if int(x) > high]
    if not new_ids:
        return
    new_ids.sort()
    log(f"[{account}] new uids: {new_ids}")
    seq = ",".join(str(u) for u in new_ids).encode()
    typ, msgs = M.uid("FETCH", seq, "(UID RFC822.HEADER)")
    if typ != "OK":
        return
    for item in msgs:
        if not isinstance(item, tuple):
            continue
        meta_b = item[0].decode(errors="replace")
        m_uid = re.search(r"UID (\d+)", meta_b)
        uid = m_uid.group(1) if m_uid else None
        h = message_from_bytes(item[1])
        meta = {
            "uid": uid,
            "from": _decode(h.get("From")),
            "to": _decode(h.get("To")),
            "subject": _decode(h.get("Subject")),
            "date": h.get("Date"),
        }
        write_notification(account, meta)
        log(
            f"[{account}] notified uid={uid} "
            f"from={meta['from'][:60]} subj={meta['subject'][:60]}"
        )
    set_high_uid(high_uid_path, max(new_ids))


class _AccountConn:
    """Per-account IMAP connection state with lazy reconnect."""

    def __init__(self, name: str):
        self.name = name
        self.M = None
        self.last_reconnect = 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--interval",
        type=int,
        default=int(_env("EMAIL_CLIENT_POLL_INTERVAL", "15")),
        help="poll seconds",
    )
    args = ap.parse_args()

    def log(msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    conns: dict[str, _AccountConn] = {}
    last_index_mtime = 0.0
    accounts: list[str] = []

    while True:
        # Re-read accounts.json each iteration so the daemon picks up
        # added accounts without a restart.
        try:
            idx_mtime = _index_mtime()
        except Exception:
            idx_mtime = 0.0
        if idx_mtime != last_index_mtime:
            last_index_mtime = idx_mtime
            accounts = list_accounts()
            if not accounts:
                # Triggers single-account migration on first call if applicable.
                load_accounts_index()
                accounts = list_accounts()
            log(f"polling accounts: {accounts}")

        if not accounts:
            log("no accounts registered; sleeping")
            time.sleep(args.interval)
            continue

        for name in accounts:
            conn = conns.setdefault(name, _AccountConn(name))
            high_uid_path = account_dir(name) / "high_uid.txt"
            try:
                if conn.M is None:
                    conn.M = connect(name)
                    conn.last_reconnect = time.time()
                    log(f"[{name}] connected")
                poll_once(name, conn.M, log, high_uid_path)
            except Exception as e:
                log(f"[{name}] error: {e}")
                try:
                    if conn.M:
                        conn.M.logout()
                except Exception:
                    pass
                conn.M = None
            # Reconnect every 25 min as a safety net.
            if conn.M and time.time() - conn.last_reconnect > 1500:
                try:
                    conn.M.logout()
                except Exception:
                    pass
                conn.M = None
        time.sleep(args.interval)


def _index_mtime() -> float:
    """Return mtime of accounts.json or 0 if missing."""
    from imap_client import _accounts_index_path

    p = _accounts_index_path()
    return p.stat().st_mtime if p.exists() else 0.0


if __name__ == "__main__":
    main()
