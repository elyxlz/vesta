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
import sys
import time
import uuid

from imap_tools import AND

# Reuse imap_client helpers.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from imap_client import (  # noqa: E402
    _env,
    _from_full,
    _to_full,
    account_dir,
    connect,
    list_accounts,
)

NOTIF_DIR = pathlib.Path.home() / "agent" / "notifications"


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


def poll_once(account: str, mb, log, high_uid_path: pathlib.Path) -> None:
    mb.folder.set("INBOX")
    high = get_high_uid(high_uid_path)
    if high == 0:
        # First run for this account: seed with the latest UID, do not
        # flood with backlog.
        all_uids = mb.uids("ALL")
        if all_uids:
            seed = max(int(u) for u in all_uids)
            set_high_uid(high_uid_path, seed)
            log(f"[{account}] seeded high_uid={seed}")
        return

    # imap_tools query syntax: ``UID first:*`` selects the open-ended range.
    new_msgs = list(
        mb.fetch(
            AND(uid=f"{high + 1}:*"),
            mark_seen=False,
            headers_only=True,
        )
    )
    new_msgs = [m for m in new_msgs if m.uid and int(m.uid) > high]
    if not new_msgs:
        return
    new_msgs.sort(key=lambda m: int(m.uid))
    log(f"[{account}] new uids: {[m.uid for m in new_msgs]}")
    for m in new_msgs:
        meta = {
            "uid": m.uid,
            "from": _from_full(m),
            "to": _to_full(m),
            "subject": m.subject,
            "date": m.date_str,
        }
        write_notification(account, meta)
        log(
            f"[{account}] notified uid={m.uid} "
            f"from={meta['from'][:60]} subj={meta['subject'][:60]}"
        )
    set_high_uid(high_uid_path, max(int(m.uid) for m in new_msgs))


class _AccountConn:
    """Per-account IMAP connection state with lazy reconnect."""

    def __init__(self, name: str):
        self.name = name
        self.mb = None
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
            log(f"polling accounts: {accounts}")

        if not accounts:
            log("no accounts registered; sleeping")
            time.sleep(args.interval)
            continue

        for name in accounts:
            conn = conns.setdefault(name, _AccountConn(name))
            high_uid_path = account_dir(name) / "high_uid.txt"
            try:
                if conn.mb is None:
                    conn.mb = connect(name, initial_folder=None)
                    conn.last_reconnect = time.time()
                    log(f"[{name}] connected")
                poll_once(name, conn.mb, log, high_uid_path)
            except Exception as e:
                log(f"[{name}] error: {e}")
                try:
                    if conn.mb:
                        conn.mb.logout()
                except Exception:
                    pass
                conn.mb = None
            # Reconnect every 25 min as a safety net.
            if conn.mb and time.time() - conn.last_reconnect > 1500:
                try:
                    conn.mb.logout()
                except Exception:
                    pass
                conn.mb = None
        time.sleep(args.interval)


def _index_mtime() -> float:
    """Return mtime of accounts.json or 0 if missing."""
    from imap_client import _accounts_index_path

    p = _accounts_index_path()
    return p.stat().st_mtime if p.exists() else 0.0


if __name__ == "__main__":
    main()
