"""Daemon lifecycle for the tricount CLI: the whole contract, owned here.

start spawns the watcher detached and records its pid, stop is the SIGTERM that ends it, and
status answers from that record alone. The watcher answers no probe, so a child still alive a
moment after the spawn is what start reads as up.
"""

import contextlib
import io
import json
import os
import pathlib as pl
import signal
import subprocess
import sys
import time

NAME = "tricount"
DAEMONS_DIR = pl.Path.home() / "agent/data/daemons"
PIDFILE = DAEMONS_DIR / f"{NAME}.pid"
LOG = pl.Path.home() / "agent/logs" / f"{NAME}.log"
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
            [sys.argv[0], "serve", "--notifications-dir", str(pl.Path.home() / "agent/notifications")],
            start_new_session=True,
            stdout=log,
            stderr=log,
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


def _stop() -> int:
    pid = live_pid()
    if pid is None:
        print(json.dumps({"status": "already_stopped"}))
        return 0
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if live_pid() is None:
            PIDFILE.unlink(missing_ok=True)
            print(json.dumps({"status": "stopped"}))
            return 0
        time.sleep(POLL_SECS)
    return _fail(f"{NAME} still running {STOP_TIMEOUT_SECS}s after SIGTERM (pid={pid})")


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
