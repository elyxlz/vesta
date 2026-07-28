"""Daemon lifecycle for the voice server: the whole contract, owned here.

start registers the port with vestad and records it beside the pid, stop is a SIGTERM the
server reads as deliberate, and status answers from those two records alone.
"""

import contextlib
import io
import json
import os
import pathlib as pl
import shutil
import signal
import subprocess
import sys
import time

NAME = "voice"
DAEMONS_DIR = pl.Path.home() / "agent/data/daemons"
PIDFILE = DAEMONS_DIR / f"{NAME}.pid"
PORTFILE = DAEMONS_DIR / f"{NAME}.port"
LOG = pl.Path.home() / "agent/logs" / f"{NAME}.log"
# /health needs no provider key, so it answers before any STT or TTS credential exists.
READY_URL_PATH = "health"
USAGE = "Usage: voice-keys daemon <start|stop|restart|status>"
POLL_SECS = 0.5
# One hung connection must not eat the whole readiness budget.
PROBE_TIMEOUT_SECS = 2


def _budget(name: str, default: int) -> int:
    return int(os.environ[name]) if name in os.environ else default


READY_TIMEOUT_SECS = _budget("DAEMON_READY_TIMEOUT_SECS", 30)
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


def _register_port() -> str | None:
    result = subprocess.run(["register-service", NAME], capture_output=True, text=True, check=False)
    port = result.stdout.strip()
    return port if result.returncode == 0 and port else None


def _ready(port: str) -> bool:
    probe = subprocess.run(
        ["curl", "-m", str(PROBE_TIMEOUT_SECS), "-fsS", "-o", "/dev/null", f"http://localhost:{port}/{READY_URL_PATH}"],
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


def _abandon(child: subprocess.Popen[bytes], message: str) -> int:
    """A start that gives up takes its child and both records with it: a daemon nothing can reach,
    with records that say it is up, reads as running and turns every later start into a no-op."""
    child.terminate()
    try:
        child.wait(timeout=STOP_TIMEOUT_SECS)
    except subprocess.TimeoutExpired:
        child.kill()
        child.wait()
    PIDFILE.unlink(missing_ok=True)
    PORTFILE.unlink(missing_ok=True)
    return _fail(message)


def _start() -> int:
    if live_pid() is not None:
        print(json.dumps({"status": "already_running"}))
        return 0
    binary = shutil.which("voice-server")
    if binary is None:
        return _fail("voice-server is not on PATH; run `uv tool install --editable ~/agent/skills/voice/cli` first")
    port = _register_port()
    if port is None:
        return _fail(f"could not register {NAME} with vestad; not launching")
    DAEMONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PORTFILE.write_text(port)
    with LOG.open("ab") as log:
        child = subprocess.Popen([binary], env={**os.environ, "SKILL_PORT": port}, start_new_session=True, stdout=log, stderr=log)
    PIDFILE.write_text(str(child.pid))
    deadline = time.monotonic() + READY_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return _abandon(child, f"{NAME} exited during startup; see {LOG}")
        if _ready(port):
            print(json.dumps({"status": "started"}))
            return 0
        time.sleep(POLL_SECS)
    return _abandon(child, f"{NAME} never answered on port {port}; see {LOG}")


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
