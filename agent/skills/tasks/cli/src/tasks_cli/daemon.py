"""Daemon lifecycle for the tasks CLI: the whole contract, owned here.

start registers the port with vestad and records it beside the pid, stop is a SIGTERM the
serve path reads as deliberate, and status answers from those two records alone.
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

NAME = "tasks"
DAEMONS_DIR = pl.Path.home() / "agent/data/daemons"
PIDFILE = DAEMONS_DIR / f"{NAME}.pid"
PORTFILE = DAEMONS_DIR / f"{NAME}.port"
LOG = pl.Path.home() / "agent/logs" / f"{NAME}.log"
# The task list is the first thing the HTTP server can answer, so it doubles as the readiness probe.
READY_URL_PATH = "tasks"
USAGE = f"Usage: {NAME} daemon <start|stop|restart|status>"
READY_TIMEOUT_SECS = 30
STOP_TIMEOUT_SECS = 15
POLL_SECS = 0.5


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


def _register_port() -> str | None:
    result = subprocess.run(["register-service", NAME], capture_output=True, text=True, check=False)
    port = result.stdout.strip()
    return port if result.returncode == 0 and port else None


def _ready(port: str) -> bool:
    probe = subprocess.run(
        ["curl", "-fsS", "-o", "/dev/null", f"http://localhost:{port}/{READY_URL_PATH}"],
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


def _start() -> int:
    if live_pid() is not None:
        print(json.dumps({"status": "already_running"}))
        return 0
    port = _register_port()
    if port is None:
        return _fail(f"could not register {NAME} with vestad; not launching")
    DAEMONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PORTFILE.write_text(port)
    with LOG.open("ab") as log:
        child = subprocess.Popen([sys.argv[0], "serve", "--port", port], start_new_session=True, stdout=log, stderr=log)
    PIDFILE.write_text(str(child.pid))
    deadline = time.monotonic() + READY_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if child.poll() is not None:
            PIDFILE.unlink(missing_ok=True)
            return _fail(f"{NAME} exited during startup; see {LOG}")
        if _ready(port):
            print(json.dumps({"status": "started"}))
            return 0
        time.sleep(POLL_SECS)
    return _fail(f"{NAME} never answered on port {port}; see {LOG}")


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
            PORTFILE.unlink(missing_ok=True)
            print(json.dumps({"status": "stopped"}))
            return 0
        time.sleep(POLL_SECS)
    return _fail(f"{NAME} still running {STOP_TIMEOUT_SECS}s after SIGTERM (pid={pid})")


def _status() -> int:
    """Reads the port start recorded, never registration, so status answers instantly and
    truthfully while vestad is down."""
    running = live_pid() is not None
    port = PORTFILE.read_text().strip() if running and PORTFILE.exists() else ""
    print(json.dumps({"running": running, "port": int(port) if port else None}))
    return 0


def daemon_cmd(action: str) -> int:
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
