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
POLL_SECS = 0.5
# How long a start that lost the record claim waits for the rival start to resolve.
CLAIM_WAIT_SECS = 3
# One hung connection must not eat the whole readiness budget.
PROBE_TIMEOUT_SECS = 2


def _budget(name: str, default: int) -> int:
    return int(os.environ[name]) if name in os.environ else default


# 120, not 30. A readiness budget is a bet about disk speed, and boot is when that bet is worst:
# every call cold, nothing in page cache, several daemons starting at once. A miss is not a retry.
# `_abandon` TERMs then KILLs a child that `child.poll()` just showed to be ALIVE, so a daemon that
# is merely slow to import is destroyed and the caller is handed an error that reads like a crash.
# For this daemon that means no task alert fires at all until someone notices, which is the
# whole point of it. Raising the ceiling costs a healthy start nothing: it returns the moment
# the port answers, in about a second.
READY_TIMEOUT_SECS = _budget("DAEMON_READY_TIMEOUT_SECS", 120)
STOP_TIMEOUT_SECS = _budget("DAEMON_STOP_TIMEOUT_SECS", 15)


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def _starttime(pid: int) -> int | None:
    """Field 22 of /proc/<pid>/stat: the process start time in clock ticks since boot.

    A recycled pid cannot share the original's starttime, because the process that took the pid
    necessarily started later, so (pid, starttime) is a stable identity. Returns None where /proc
    is unreadable, which drops the caller back to a bare pid-existence check.
    """
    try:
        stat = pl.Path(f"/proc/{pid}/stat").read_text()
        # comm is a bracketed field that may itself contain spaces and parentheses, so the
        # numbered fields resume after the LAST ')'.
        return int(stat[stat.rindex(")") + 2 :].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _record(pid: int) -> str:
    """The pid record: "<pid> <starttime>", or a bare pid where the starttime is unavailable.

    A bare pid is the honest form of "identity unknown", and live_pid() reads it the legacy way
    rather than as a mismatch. Writing the string "None" into the record would mean the same thing
    while looking like data.
    """
    started = _starttime(pid)
    return f"{pid} {started}" if started is not None else str(pid)


def live_pid() -> int | None:
    """The recorded pid, but only while it is still the process that was recorded.

    os.kill(pid, 0) answers "does some process hold this pid", never "is this still mine". The
    records outlive the container while a fresh pid namespace renumbers from low values, so a
    reused pid otherwise reads as a healthy daemon, every idempotent start skips it, and the
    service is silently down with its one health check reporting health it never measured.
    """
    try:
        record = PIDFILE.read_text().split()
        pid = int(record[0])
        os.kill(pid, 0)
    except (FileNotFoundError, IndexError, ValueError, ProcessLookupError, PermissionError):
        return None
    # LEGACY(remove-when: no daemon record predating the release that ships this check remains, i.e.
    # every box has restarted its daemons at least once on this version): a record written by the
    # old code is a bare pid. Trust it as before rather than reading the absence of a starttime as a
    # mismatch, because an upgrade must not declare a live daemon dead and let a second stack beside
    # it. Once records have converged, an unparseable second field should read as dead, not as legacy.
    if len(record) > 1 and record[1].isdigit():
        current = _starttime(pid)
        if current is not None and current != int(record[1]):
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
        handle.write(_record(pid))
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
    port = _register_port()
    if port is None:
        PIDFILE.unlink(missing_ok=True)
        return _fail(f"could not register {NAME} with vestad; not launching")
    PORTFILE.write_text(port)
    with LOG.open("ab") as log:
        child = subprocess.Popen(
            [sys.argv[0], "serve", "--port", port], env={**os.environ, "PYTHONUNBUFFERED": "1"}, start_new_session=True, stdout=log, stderr=log
        )
    PIDFILE.write_text(_record(child.pid))
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
