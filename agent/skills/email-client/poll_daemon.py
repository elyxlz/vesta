#!/usr/bin/env python3
"""IMAP poll daemon.

Polls the user's INBOX every N seconds and writes a notification JSON
into ~/agent/notifications/ for each new message. Auto-refreshes the
OAuth token via the imap_client helper. No promo blocklist by default;
the agent decides what to surface to the user.
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
from imap_client import _env, _state_dir, connect  # noqa: E402

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


def write_notification(meta: dict) -> None:
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "imap-mail",
        "type": "email",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "from": meta["from"],
        "to": meta.get("to", ""),
        "subject": meta["subject"],
        "date": meta["date"],
        "uid": meta["uid"],
    }
    fname = f"imap-mail-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json"
    (NOTIF_DIR / fname).write_text(json.dumps(notif, ensure_ascii=False, indent=2))


def get_high_uid(path: pathlib.Path) -> int:
    if path.exists():
        return int(path.read_text().strip() or 0)
    return 0


def set_high_uid(path: pathlib.Path, n: int) -> None:
    path.write_text(str(n))


def poll_once(M, log, high_uid_path: pathlib.Path) -> None:
    M.select("INBOX", readonly=True)
    high = get_high_uid(high_uid_path)
    if high == 0:
        # First run: seed with the latest UID, do not flood with backlog.
        typ, data = M.uid("SEARCH", "ALL")
        ids = data[0].split()
        if ids:
            set_high_uid(high_uid_path, int(ids[-1]))
            log(f"seeded high_uid={ids[-1].decode()}")
        return

    typ, data = M.uid("SEARCH", f"UID {high + 1}:*")
    if typ != "OK" or not data or not data[0]:
        return
    raw = data[0].split()
    new_ids = [int(x) for x in raw if int(x) > high]
    if not new_ids:
        return
    new_ids.sort()
    log(f"new uids: {new_ids}")
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
        write_notification(meta)
        log(f"notified uid={uid} from={meta['from'][:60]} subj={meta['subject'][:60]}")
    set_high_uid(high_uid_path, max(new_ids))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--interval",
        type=int,
        default=int(_env("IMAP_MAIL_POLL_INTERVAL", "15")),
        help="poll seconds",
    )
    args = ap.parse_args()

    high_uid_path = _state_dir() / "high_uid.txt"

    def log(msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    M = None
    last_reconnect = 0
    while True:
        try:
            if M is None:
                M = connect()
                last_reconnect = time.time()
                log("connected")
            poll_once(M, log, high_uid_path)
        except Exception as e:
            log(f"error: {e}")
            try:
                if M:
                    M.logout()
            except Exception:
                pass
            M = None
        # Reconnect every 25 min as a safety net.
        if M and time.time() - last_reconnect > 1500:
            try:
                M.logout()
            except Exception:
                pass
            M = None
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
