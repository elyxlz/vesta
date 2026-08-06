"""App Chat daemon.

Owns the app-chat channel: it runs the skill's HTTP service (POST /message intake, GET /history, and
GET /ws, the replay-free live chat stream), and accepts CLI commands via a Unix socket to send replies
(`app-chat send` -> persist a `chat` event, fan it to the /ws subscribers, send a user notification to
vestad so a backgrounded client gets one). Durability is the skill's own store, so a reply succeeds even
with no client connected; the live echo fans out in-process to whoever is on /ws.

`app-chat daemon start|stop|restart|status` owns the process lifecycle: start registers the port with
vestad and records it beside the pid, stop is a SIGTERM the serve path reads as deliberate, and status
answers from those two records alone.
"""

import argparse
import asyncio
import contextlib
import functools
import io
import json
import os
import pathlib as pl
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aiohttp import web

from .service import ServiceState, create_app
from .store import Store, StoredEvent, store_path

NAME = "app-chat"
DAEMONS_DIR = pl.Path.home() / "agent/data/daemons"
PIDFILE = DAEMONS_DIR / f"{NAME}.pid"
PORTFILE = DAEMONS_DIR / f"{NAME}.port"
LOG = pl.Path.home() / "agent/logs" / f"{NAME}.log"
# The service answers /health with nothing connected to it, so it doubles as the readiness probe.
READY_URL_PATH = "health"
USAGE = f"Usage: {NAME} daemon <start|stop|restart|status>"
POLL_SECS = 0.5
# How long a start that lost the record claim waits for the rival start to resolve.
CLAIM_WAIT_SECS = 3
# One hung connection must not eat the whole readiness budget.
PROBE_TIMEOUT_SECS = 2
USER_NOTIFICATION_TIMEOUT = 10.0

USER_NOTIFICATION = pl.Path.home() / "agent" / "skills" / "vestad" / "scripts" / "user-notification"


def _budget(name: str, default: int) -> int:
    return int(os.environ[name]) if name in os.environ else default


READY_TIMEOUT_SECS = _budget("DAEMON_READY_TIMEOUT_SECS", 30)
STOP_TIMEOUT_SECS = _budget("DAEMON_STOP_TIMEOUT_SECS", 15)


def _fail(message: str) -> int:
    print(json.dumps({"error": message}), file=sys.stderr)
    return 1


def default_data_dir() -> pl.Path:
    return pl.Path.home() / ".app-chat"


def default_notifications_dir() -> pl.Path:
    return pl.Path.home() / "agent" / "notifications"


def _sock_path(data_dir: pl.Path) -> pl.Path:
    return data_dir / "app-chat.sock"


@dataclass
class DaemonState:
    sock_path: pl.Path
    data_dir: pl.Path
    notifications_dir: pl.Path
    port: int
    service: ServiceState
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    asked_to_stop: bool = False


def _send_user_notification(text: str) -> None:
    """Best-effort: tell vestad an app reply went out so it toasts + pushes. A failure here never fails
    the reply (durability + the live echo already happened); it only skips the toast/push, so swallow a
    spawn error and cap a hung script."""
    agent = os.environ.get("AGENT_NAME")
    if agent is None or not USER_NOTIFICATION.exists():
        return
    preview = text[:180]
    try:
        subprocess.run(
            [str(USER_NOTIFICATION), "message", agent, preview],
            check=False,
            capture_output=True,
            timeout=USER_NOTIFICATION_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log(f"user notification failed: {exc}")


def cmd_serve(args: argparse.Namespace) -> None:
    data_dir = pl.Path(args.data_dir or default_data_dir())
    data_dir.mkdir(parents=True, exist_ok=True)
    port = str(args.port) if args.port is not None else _register_port()
    if port is None:
        sys.exit(_fail(f"could not register {NAME} with vestad"))

    service = ServiceState(Store(store_path(data_dir)), default_notifications_dir())
    state = DaemonState(
        sock_path=_sock_path(data_dir),
        data_dir=data_dir,
        notifications_dir=default_notifications_dir(),
        port=int(port),
        service=service,
    )
    asyncio.run(_run(state))


def _begin_shutdown(state: DaemonState, sig: signal.Signals) -> None:
    """SIGTERM is what `app-chat daemon stop` sends, so it is the one exit the agent asked for;
    every other way out is news the agent needs."""
    state.asked_to_stop = sig == signal.SIGTERM
    state.shutdown.set()


async def _run(state: DaemonState) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, functools.partial(_begin_shutdown, state, sig))

    runner = web.AppRunner(create_app(state.service))
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=state.port)
    await site.start()
    _log(f"service on port {state.port}")
    socket_task = asyncio.create_task(_socket_server(state))
    try:
        await state.shutdown.wait()
        socket_task.cancel()
        await asyncio.gather(socket_task, return_exceptions=True)
    finally:
        await runner.cleanup()
        state.service.store.close()
        state.sock_path.unlink(missing_ok=True)
        if not state.asked_to_stop:
            write_death_notification(state.notifications_dir)


def write_death_notification(notifications_dir: pl.Path) -> None:
    notifications_dir.mkdir(parents=True, exist_ok=True)
    notification = {
        "source": "app-chat",
        "type": "daemon_died",
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    path = notifications_dir / f"{int(time.time() * 1e6)}-app-chat-daemon_died.json"
    path.write_text(json.dumps(notification))


async def _socket_server(state: DaemonState) -> None:
    state.sock_path.unlink(missing_ok=True)

    server = await asyncio.start_unix_server(functools.partial(_handle_socket_conn, state), path=str(state.sock_path))
    state.sock_path.chmod(0o600)
    _log(f"socket server: {state.sock_path}")

    try:
        await state.shutdown.wait()
    finally:
        server.close()
        await server.wait_closed()


async def _handle_socket_conn(state: DaemonState, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        data = await asyncio.wait_for(reader.read(65536), timeout=30.0)
        request = json.loads(data.decode())
        command = request["command"]

        if command == "send":
            message = request["message"].strip()
            if not message:
                response: dict[str, object] = {"error": "empty message"}
            else:
                event: StoredEvent = {"type": "chat", "ts": datetime.now(UTC).isoformat(), "text": message}
                state.service.store.append(event)
                state.service.emit(event)
                await asyncio.to_thread(_send_user_notification, message)
                response = {"ok": True, "message": message, "id": event["id"]}
        elif command == "status":
            response = {"ok": True, "port": state.port, "clients": len(state.service.subscribers)}
        else:
            response = {"error": f"unknown command: {command}"}

        writer.write(json.dumps(response).encode())
        await writer.drain()
    except (json.JSONDecodeError, KeyError, TimeoutError, OSError) as exc:
        _log(f"socket error: {exc}")
    finally:
        writer.close()
        await writer.wait_closed()


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


def _log(message: str) -> None:
    print(f"[app-chat] {message}", file=sys.stderr, flush=True)
