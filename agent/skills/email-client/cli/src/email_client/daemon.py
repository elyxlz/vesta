#!/usr/bin/env python3
"""Daemon lifecycle for the poll daemon: the whole contract, owned here.

start re-invokes ``email-client poll`` detached and records its pid, stop is the SIGTERM that
ends it, and status answers from that record alone. The poller answers no probe and serves no
port, so a child still alive a moment after the spawn is what start reads as up.

Imports nothing from the account layer, so the four verbs run without pulling in imap_tools/msal
while the poller itself loads the account layer under the same interpreter.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

NAME = "email-client"
DAEMONS_DIR = pathlib.Path.home() / "agent/data/daemons"
PIDFILE = DAEMONS_DIR / f"{NAME}.pid"
LOG = pathlib.Path.home() / "agent/logs" / f"{NAME}.log"
USAGE = f"Usage: {NAME} daemon <start|stop|restart|status>"
POLL_SECS = 0.5
# How long a start that lost the record claim waits for the rival start to resolve.
CLAIM_WAIT_SECS = 3
SETTLE_SECS = 2


def _budget(name: str, default: int) -> int:
    return int(os.environ[name]) if name in os.environ else default


STOP_TIMEOUT_SECS = _budget("DAEMON_STOP_TIMEOUT_SECS", 15)


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def live_pid() -> int | None:
    try:
        pid = int(PIDFILE.read_text().strip())
        os.kill(pid, 0)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None
    return pid


def _claim(pid: int) -> bool:
    try:
        record = os.open(PIDFILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False
    with os.fdopen(record, "w") as handle:
        handle.write(str(pid))
    return True


def _claim_start() -> int | None:
    """Takes the pid record exclusively for this start, so a start that loses the claim answers
    already_running instead of stacking a daemon beside the winner's. A record no process stands
    behind is cleared and taken over, which is the one path on which two starts can both spawn, and
    the duplicate loses on its own resources. None means this start owns the record and everything
    it later removes; anything else is this start's whole answer."""
    if _claim(os.getpid()):
        return None
    deadline = time.monotonic() + CLAIM_WAIT_SECS
    while time.monotonic() < deadline:
        if live_pid() is not None:
            print(json.dumps({"status": "already_running"}))
            return 0
        if not PIDFILE.exists():
            break
        time.sleep(POLL_SECS)
    PIDFILE.unlink(missing_ok=True)
    if _claim(os.getpid()):
        return None
    return _fail(f"another {NAME} start holds {PIDFILE}")


def _start() -> int:
    if live_pid() is not None:
        print(json.dumps({"status": "already_running"}))
        return 0
    DAEMONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    answer = _claim_start()
    if answer is not None:
        return answer
    with LOG.open("ab") as log:
        child = subprocess.Popen(
            [sys.argv[0], "poll"], env={**os.environ, "PYTHONUNBUFFERED": "1"}, start_new_session=True, stdout=log, stderr=log
        )
    PIDFILE.write_text(str(child.pid))
    time.sleep(SETTLE_SECS)
    if child.poll() is None:
        print(json.dumps({"status": "started"}))
        return 0
    # A start that gives up takes its record with it: a record that says a dead daemon is up
    # reads as running and turns every later start into a no-op.
    PIDFILE.unlink(missing_ok=True)
    return _fail(f"{NAME} exited during startup; see {LOG}")


def _await_gone(deadline: float) -> bool:
    """Waits out the daemon until a deadline shared with the rest of this stop. Answers whether
    the process the record names is gone."""
    while time.monotonic() < deadline:
        if live_pid() is None:
            return True
        time.sleep(POLL_SECS)
    return live_pid() is None


def _stop() -> int:
    """SIGTERM then, for a daemon that ignored it, SIGKILL, both inside the one stop budget,
    so the verb ends the daemon rather than handing back a record it cannot honour. A daemon
    that exits between the check and the signal is the stop it was asked for, not an error."""
    pid = live_pid()
    if pid is None:
        print(json.dumps({"status": "already_stopped"}))
        return 0
    started = time.monotonic()
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGTERM)
    # Two thirds of the budget in, a daemon that has not honoured SIGTERM is killed instead, and
    # the remainder is what reaps it. Read here, not at import, so the budget in force is the one
    # the caller set.
    if not _await_gone(started + STOP_TIMEOUT_SECS * 2 // 3):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
        if not _await_gone(started + STOP_TIMEOUT_SECS):
            return _fail(f"{NAME} still running {STOP_TIMEOUT_SECS}s after SIGTERM then SIGKILL (pid={pid})")
    PIDFILE.unlink(missing_ok=True)
    print(json.dumps({"status": "stopped"}))
    return 0


def _status() -> int:
    print(json.dumps({"running": live_pid() is not None, "port": None}))
    return 0


def daemon_cmd(action: str) -> int:
    if action in ("", "-h", "--help", "help"):
        print(USAGE)
        return 0
    if action == "start":
        return _start()
    if action == "stop":
        return _stop()
    if action == "restart":
        # One verb, one line of output: the stop half is swallowed, and a stop that failed
        # must not be followed by a start onto a daemon that is still there.
        with contextlib.redirect_stdout(io.StringIO()):
            stopped = _stop()
        return _start() if stopped == 0 else stopped
    if action == "status":
        return _status()
    print(USAGE, file=sys.stderr)
    return 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv[:1] == ["daemon"]:
        argv = argv[1:]
    raise SystemExit(daemon_cmd(argv[0] if argv else ""))
