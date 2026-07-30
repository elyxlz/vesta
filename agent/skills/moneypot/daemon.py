"""Daemon lifecycle for the moneypot HTTP API: the whole contract, owned here.

start registers the port with vestad and records it beside the pid, stop is a SIGTERM the
serve path reads as deliberate, and status answers from those two records alone.

The CLI stays the primary surface; this only governs the optional HTTP API in server.py, which
exists so another app can read the same pot data over a port.
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

NAME = "moneypot"
DAEMONS_DIR = pl.Path.home() / "agent/data/daemons"
PIDFILE = DAEMONS_DIR / f"{NAME}.pid"
PORTFILE = DAEMONS_DIR / f"{NAME}.port"
LOG = pl.Path.home() / "agent/logs" / f"{NAME}.log"
# /health is the one route that answers without the api key, so it is the readiness probe.
READY_URL_PATH = "health"
USAGE = f"Usage: {NAME} daemon <start|stop|restart|status>"
POLL_SECS = 0.5
# How long a start that lost the record claim waits for the rival start to resolve.
CLAIM_WAIT_SECS = 3
# One hung connection must not eat the whole readiness budget.
PROBE_TIMEOUT_SECS = 2


def _budget(name: str, default: int) -> int:
    return int(os.environ[name]) if name in os.environ else default


READY_TIMEOUT_SECS = _budget("DAEMON_READY_TIMEOUT_SECS", 30)
STOP_TIMEOUT_SECS = _budget("DAEMON_STOP_TIMEOUT_SECS", 15)


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def _alive(pid: int) -> bool:
    """True only for a process that is actually running.

    A signal-0 probe cannot answer this: start exits once it has spawned the daemon, so the daemon
    reparents to init and a dead one's pid lingers unreaped, answering the probe like a live
    process. Without this, a stopped daemon reads as running: stop reports it would not die when it
    is already gone, status claims a corpse is live, and the next start no-ops onto nothing.
    /proc's state code distinguishes the corpse; the comm field can hold spaces and parens, so the
    state is read relative to its closing paren rather than by splitting on whitespace.
    (Same reasoning as `_alive` in the browser skill's handover.)
    """
    try:
        stat = (pl.Path("/proc") / str(pid) / "stat").read_text()
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return False
    comm_end = stat.rfind(") ")
    if comm_end == -1:
        return False
    return stat[comm_end + 2] != "Z"


def live_pid() -> int | None:
    try:
        pid = int(PIDFILE.read_text().strip())
        os.kill(pid, 0)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        return None
    return pid if _alive(pid) else None


def _register_port() -> str | None:
    """Registered private: the API is read with the app credential (or a minted service key), so it
    never needs to load for an anonymous browser."""
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


def _await_ready(child: subprocess.Popen[bytes], port: str) -> int:
    """Holds the start open until the daemon it spawned answers on its port, which is what lets
    the caller's next line use the service."""
    deadline = time.monotonic() + READY_TIMEOUT_SECS
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return _abandon(child, f"{NAME} exited during startup; see {LOG}")
        if _ready(port):
            print(json.dumps({"status": "started"}))
            return 0
        time.sleep(POLL_SECS)
    return _abandon(child, f"{NAME} never answered on port {port}; see {LOG}")


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


def _serve_argv(port: str) -> list[str]:
    """The daemon runs the skill's own server module, so the launch does not depend on how the CLI
    itself was invoked (console script, `python3 moneypot.py`, or the `moneypot` shell launcher)."""
    return [sys.executable, str(pl.Path(__file__).resolve().parent / "server.py"), "--port", port]


def _start() -> int:
    if live_pid() is not None:
        print(json.dumps({"status": "already_running"}))
        return 0
    DAEMONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    answer = _claim_start()
    if answer is not None:
        return answer
    port = _register_port()
    if port is None:
        PIDFILE.unlink(missing_ok=True)
        return _fail(f"could not register {NAME} with vestad; not launching")
    PORTFILE.write_text(port)
    with LOG.open("ab") as log:
        child = subprocess.Popen(_serve_argv(port), start_new_session=True, stdout=log, stderr=log)
    PIDFILE.write_text(str(child.pid))
    return _await_ready(child, port)


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
    PORTFILE.unlink(missing_ok=True)
    print(json.dumps({"status": "stopped"}))
    return 0


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
