#!/usr/bin/env python3
"""IMAP push/poll daemon (multi-account).

Watches each registered account's notify folders (INBOX by default; set
per account with ``email-client notify``) and writes a notification JSON
into ~/agent/notifications/ for each new message. Uses IMAP IDLE for
real-time push where the server advertises the capability, falling back
to interval polling otherwise. Auto-refreshes the OAuth token via the
imap_client helper on every reconnect.

One worker thread per (account, folder), each holding its own persistent
IMAP connection. The supervisor reads each account's watch list and
starts/stops workers as accounts or folders are added or removed, so no
restart is needed. Each (account, folder) keeps its own high-UID
watermark under ``$EMAIL_CLIENT_DIR/accounts/<name>/`` (``high_uid.txt``
for INBOX, ``high_uid_<folder>.txt`` otherwise); the first run seeds it
with the latest UID so there is no backlog flood.

Notifications carry source ``email-client`` and ``account`` + ``folder``
fields naming the source mailbox. The filename includes both so
simultaneous notifications never collide.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import signal
import sys
import threading
import time
import uuid

from imap_tools import AND

# Reuse imap_client helpers. realpath (not abspath) so this resolves through the
# ~/.email-client/poll_daemon.py symlink back to the skill's real directory.
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import contextlib

import daemon_lifecycle
from imap_client import (
    _env,
    _from_full,
    _state_dir,
    _to_full,
    account_dir,
    connect,
    list_accounts,
    notify_folders,
)

NOTIF_DIR = pathlib.Path.home() / "agent" / "notifications"
# Bounded wait for worker threads to notice a stop_event and exit, so shutdown
# on SIGTERM cannot hang forever on a wedged IMAP connection.
WORKER_JOIN_TIMEOUT_SECS = 5

# Re-issue IDLE well under the 29-minute RFC 2177 ceiling; this also bounds
# how quickly a worker notices a shutdown request.
IDLE_TIMEOUT_SECS = 270
# Tear down and reconnect periodically so the OAuth access token is
# refreshed and the IDLE session is reset against idle-timeout proxies.
RECONNECT_SECS = 1500
# Backoff after a connection error before a worker retries.
RETRY_DELAY_SECS = 30
# How often the supervisor checks accounts.json for added/removed accounts.
INDEX_CHECK_SECS = 10
# Cap one fetch batch so a long offline period doesn't time out a single
# IMAP transaction trying to pull thousands of headers. Caller re-enters
# on the next IDLE/poll cycle to pick up the remaining backlog.
FETCH_BATCH_LIMIT = 500


def _sanitize_folder(folder: str) -> str:
    """Filesystem-safe token for a folder name (for the watermark filename)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", folder)


def watermark_path(account: str, folder: str) -> pathlib.Path:
    """Per-(account, folder) high-UID watermark path.

    INBOX keeps the legacy ``high_uid.txt`` name so existing installs do
    not lose their watermark on upgrade.
    """
    base = account_dir(account)
    if folder == "INBOX":
        return base / "high_uid.txt"
    return base / f"high_uid_{_sanitize_folder(folder)}.txt"


def write_notification(account: str, folder: str, meta: dict) -> None:
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "email-client",
        "type": "email",
        # Email pools by default so routine mail doesn't preempt the agent; the user adds interrupt rules
        # (e.g. --keyword urgent, a specific sender) for the messages that should reach them immediately.
        "interrupt": False,
        "account": account,
        "folder": folder,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "from": meta["from"],
        "to": meta.get("to", ""),
        "subject": meta["subject"],
        "date": meta["date"],
        "uid": meta["uid"],
    }
    fname = f"email-client-{account}-{_sanitize_folder(folder)}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json"
    # tmp + rename so the agent's watchfiles loop never reads a truncated file.
    final = NOTIF_DIR / fname
    tmp = NOTIF_DIR / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, ensure_ascii=False, indent=2))
    os.replace(tmp, final)


def get_high_uid(path: pathlib.Path) -> int:
    if path.exists():
        return int(path.read_text().strip() or 0)
    return 0


def set_high_uid(path: pathlib.Path, n: int) -> None:
    path.write_text(str(n))


def emit_new(account: str, folder: str, mb, log, high_uid_path: pathlib.Path) -> None:
    """Notify on every message in ``folder`` with UID above the watermark."""
    mb.folder.set(folder)
    high = get_high_uid(high_uid_path)
    if high == 0:
        # First run for this account: seed with the latest UID, do not
        # flood with backlog.
        all_uids = mb.uids("ALL")
        if all_uids:
            seed = max(int(u) for u in all_uids)
            set_high_uid(high_uid_path, seed)
            log(f"[{account}:{folder}] seeded high_uid={seed}")
        return

    # imap_tools query syntax: ``UID first:*`` selects the open-ended range.
    new_msgs = list(
        mb.fetch(
            AND(uid=f"{high + 1}:*"),
            mark_seen=False,
            headers_only=True,
            limit=FETCH_BATCH_LIMIT,
        )
    )
    new_msgs = [m for m in new_msgs if m.uid and int(m.uid) > high]
    if not new_msgs:
        return
    new_msgs.sort(key=lambda m: int(m.uid))
    log(f"[{account}:{folder}] new uids: {[m.uid for m in new_msgs]}")
    for m in new_msgs:
        meta = {
            "uid": m.uid,
            "from": _from_full(m),
            "to": _to_full(m),
            "subject": m.subject,
            "date": m.date_str,
        }
        write_notification(account, folder, meta)
        log(f"[{account}:{folder}] notified uid={m.uid} from={meta['from'][:60]} subj={meta['subject'][:60]}")
    set_high_uid(high_uid_path, max(int(m.uid) for m in new_msgs))


def folder_worker(account: str, folder: str, interval: int, log, stop_event: threading.Event) -> None:
    """Watch one ``(account, folder)`` until ``stop_event`` is set.

    Holds a persistent connection: waits on IMAP IDLE when available,
    otherwise sleeps ``interval`` between checks. Reconnects on error
    (with backoff) and on the periodic refresh interval.
    """
    high_uid_path = watermark_path(account, folder)
    while not stop_event.is_set():
        mb = None
        try:
            mb = connect(account, initial_folder=folder)
            use_idle = "IDLE" in (mb.client.capabilities or ())
            log(f"[{account}:{folder}] connected ({'IDLE' if use_idle else 'poll'} mode)")
            emit_new(account, folder, mb, log, high_uid_path)
            session_start = time.monotonic()
            while not stop_event.is_set():
                if time.monotonic() - session_start > RECONNECT_SECS:
                    break
                if use_idle:
                    # wait() runs the full IDLE start/poll/stop cycle and
                    # returns on a server push or when the timeout expires.
                    mb.idle.wait(timeout=IDLE_TIMEOUT_SECS)
                    if stop_event.is_set():
                        break
                    emit_new(account, folder, mb, log, high_uid_path)
                else:
                    if stop_event.wait(interval):
                        break
                    emit_new(account, folder, mb, log, high_uid_path)
        except Exception as e:
            log(f"[{account}:{folder}] error: {e}; retrying in {RETRY_DELAY_SECS}s")
            stop_event.wait(RETRY_DELAY_SECS)
        finally:
            if mb is not None:
                with contextlib.suppress(Exception):
                    mb.logout()
    log(f"[{account}:{folder}] worker stopped")


def write_daemon_died_notification(reason: str) -> None:
    NOTIF_DIR.mkdir(parents=True, exist_ok=True)
    notif = {
        "source": "email-client",
        "type": "daemon_died",
        "reason": reason,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
    }
    fname = f"email-client-daemon_died-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}.json"
    final = NOTIF_DIR / fname
    tmp = NOTIF_DIR / f"{fname}.tmp"
    tmp.write_text(json.dumps(notif, ensure_ascii=False, indent=2))
    os.replace(tmp, final)


def desired_workers() -> set[tuple[str, str]]:
    """The set of ``(account, folder)`` pairs that should be watched now."""
    wanted: set[tuple[str, str]] = set()
    for account in list_accounts():
        for folder in notify_folders(account):
            wanted.add((account, folder))
    return wanted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--interval",
        type=int,
        default=int(_env("EMAIL_CLIENT_POLL_INTERVAL", str(daemon_lifecycle.DEFAULT_POLL_INTERVAL_SECS))),
        help="poll seconds (fallback only; servers with IDLE push in real time)",
    )
    args = ap.parse_args()

    state_dir = _state_dir()

    log_lock = threading.Lock()

    def log(msg: str) -> None:
        with log_lock:
            print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

    shutdown_event = threading.Event()
    shutdown_reason = "unknown"

    def handle_signal(signum, frame):
        nonlocal shutdown_reason
        shutdown_reason = signal.Signals(signum).name
        shutdown_event.set()

    # SIGHUP fires when the controlling screen session quits; ignored so only an
    # explicit `daemon stop`/`restart` (SIGTERM) or Ctrl-C (SIGINT) triggers shutdown.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    workers: dict[tuple[str, str], tuple[threading.Thread, threading.Event]] = {}
    last_desired: set[tuple[str, str]] | None = None

    daemon_lifecycle.write_pid(state_dir)
    daemon_lifecycle.write_daemon_info(state_dir, args.interval)

    try:
        while not shutdown_event.is_set():
            try:
                wanted = desired_workers()
            except Exception as e:
                log(f"could not read accounts: {e}")
                shutdown_event.wait(INDEX_CHECK_SECS)
                continue
            if wanted != last_desired:
                last_desired = wanted
                log(f"watching: {sorted(wanted)}")
            # Low-frequency (once/day) Google OAuth client health-probe. Runs off
            # the supervisor thread so a dead upstream client is caught and
            # self-healed without any user interaction. Never allowed to crash
            # the daemon.
            try:
                import google_health

                google_health.maybe_run_daily_probe(state_dir, log)
            except Exception as e:
                log(f"[google-health] probe skipped: {e}")
            for key in list(workers):
                thread, _ = workers[key]
                if not thread.is_alive():
                    workers.pop(key)
                    log(f"[{key[0]}:{key[1]}] worker died; restarting")
            for key in wanted:
                if key not in workers:
                    account, folder = key
                    stop_event = threading.Event()
                    thread = threading.Thread(
                        target=folder_worker,
                        args=(account, folder, args.interval, log, stop_event),
                        name=f"{account}:{folder}",
                        daemon=True,
                    )
                    workers[key] = (thread, stop_event)
                    thread.start()
                    log(f"[{account}:{folder}] worker started")
            for key in list(workers):
                if key not in wanted:
                    _, stop_event = workers.pop(key)
                    stop_event.set()
                    log(f"[{key[0]}:{key[1]}] worker stopping")
            shutdown_event.wait(INDEX_CHECK_SECS)
    finally:
        for _, stop_event in workers.values():
            stop_event.set()
        for thread, _ in workers.values():
            thread.join(timeout=WORKER_JOIN_TIMEOUT_SECS)
        if daemon_lifecycle.consume_stop_requested(state_dir):
            log(f"intentional stop ({shutdown_reason}); skipping daemon_died notification")
        else:
            log(f"shutting down ({shutdown_reason}); writing daemon_died notification")
            write_daemon_died_notification(shutdown_reason)
        daemon_lifecycle.remove_pid(state_dir)


if __name__ == "__main__":
    main()
