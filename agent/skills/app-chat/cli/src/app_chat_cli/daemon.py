"""App Chat daemon.

Owns the app-chat channel: it runs the skill's HTTP service (POST /message intake, GET /history, and
GET /ws, the replay-free live chat stream), and accepts CLI commands via a Unix socket to send replies
(`app-chat send` -> persist a `chat` event, fan it to the /ws subscribers, send a user notification to
vestad so a backgrounded client gets one). Durability is the skill's own store, so a reply succeeds even
with no client connected; the live echo fans out in-process to whoever is on /ws.

`app-chat daemon start|stop|restart|status` owns the process lifecycle: start is idempotent
(a live daemon is a no-op), stop marks the shutdown as intentional so it does not fire the
`daemon_died` notification a crash would, and status reports the service port + connected chat-socket
client count to the agent in one JSON blob.
"""

import argparse
import asyncio
import functools
import json
import os
import pathlib as pl
import shutil
import signal
import subprocess
import sys
import time
import typing as tp
from dataclasses import dataclass, field
from datetime import UTC, datetime

from aiohttp import web

from .service import ServiceState, create_app
from .store import Store, StoredEvent, store_path

SOCKET_TIMEOUT = 10.0
SESSION_NAME = "app-chat"
STOP_MARKER_NAME = "stop-requested"
DAEMON_START_TIMEOUT = 15.0
DAEMON_STOP_TIMEOUT = 15.0
DAEMON_POLL_INTERVAL = 0.5
USER_NOTIFICATION_TIMEOUT = 10.0

REGISTER_SERVICE = pl.Path.home() / "agent" / "skills" / "vestad" / "scripts" / "register-service"
USER_NOTIFICATION = pl.Path.home() / "agent" / "skills" / "vestad" / "scripts" / "user-notification"


def resolve_port() -> int:
    result = subprocess.run([str(REGISTER_SERVICE), "app-chat"], capture_output=True, text=True, timeout=35, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"register-service failed: {result.stderr.strip()}")
    return int(result.stdout.strip())


def default_data_dir() -> pl.Path:
    return pl.Path.home() / ".app-chat"


def default_notifications_dir() -> pl.Path:
    return pl.Path.home() / "agent" / "notifications"


def _sock_path(data_dir: pl.Path) -> pl.Path:
    return data_dir / "app-chat.sock"


def _stop_marker_path(data_dir: pl.Path) -> pl.Path:
    return data_dir / STOP_MARKER_NAME


@dataclass
class DaemonState:
    sock_path: pl.Path
    data_dir: pl.Path
    notifications_dir: pl.Path
    port: int
    service: ServiceState
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)


def _send_user_notification(text: str) -> None:
    """Best-effort: tell vestad an app reply went out so it toasts + pushes. A failure here never fails
    the reply (durability + the live echo already happened); it only skips the toast/push, so swallow a
    spawn error and cap a hung script. The user-notification script lands with the user-notification
    primitive, so the USER_NOTIFICATION.exists() guard no-ops until then."""
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
    port = args.port if args.port is not None else resolve_port()

    service = ServiceState(Store(store_path(data_dir)), default_notifications_dir())
    state = DaemonState(
        sock_path=_sock_path(data_dir),
        data_dir=data_dir,
        notifications_dir=default_notifications_dir(),
        port=port,
        service=service,
    )
    asyncio.run(_run(state))


async def _run(state: DaemonState) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, state.shutdown.set)

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
        _consume_stop_marker_or_report_death(state.data_dir, state.notifications_dir)


def _consume_stop_marker_or_report_death(data_dir: pl.Path, notifications_dir: pl.Path) -> None:
    """A deliberate `daemon stop` drops a marker before signaling the process; consume it silently
    here. Any other exit (crash, `screen -X quit` without the marker, OOM) is unexpected, so report
    it as a `daemon_died` notification the agent can investigate."""
    marker = _stop_marker_path(data_dir)
    if marker.exists():
        marker.unlink(missing_ok=True)
        return
    write_death_notification(notifications_dir)


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


async def socket_request(sock_path: pl.Path, request: dict[str, str], timeout: float = SOCKET_TIMEOUT) -> dict[str, object]:
    try:
        reader, writer = await asyncio.open_unix_connection(str(sock_path))
        writer.write(json.dumps(request).encode())
        writer.write_eof()
        data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return tp.cast(dict[str, object], json.loads(data.decode()))
    except (OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def daemon_alive(sock_path: pl.Path) -> bool:
    if not sock_path.exists():
        return False
    result = asyncio.run(socket_request(sock_path, {"command": "status"}))
    return "error" not in result


def _print(payload: dict[str, object]) -> None:
    print(json.dumps(payload))


def cmd_daemon_start(args: argparse.Namespace) -> None:
    data_dir = pl.Path(args.data_dir or default_data_dir())
    sock_path = _sock_path(data_dir)

    if daemon_alive(sock_path):
        _print({"status": "already_running", "session": SESSION_NAME})
        return

    screen_bin = shutil.which("screen")
    if screen_bin is None:
        _print({"error": "screen is not on PATH"})
        sys.exit(1)
    app_chat_bin = shutil.which("app-chat")
    if app_chat_bin is None:
        _print({"error": "app-chat is not on PATH; install it per SKILL.md first"})
        sys.exit(1)

    # A stop marker can outlive its daemon (a stop that raced the process's death, or a failed
    # quit), so clear it before launching; this fresh daemon's own unexpected death then still
    # fires daemon_died instead of silently consuming the stale marker.
    data_dir.mkdir(parents=True, exist_ok=True)
    _stop_marker_path(data_dir).unlink(missing_ok=True)
    subprocess.run([screen_bin, "-dmS", SESSION_NAME, app_chat_bin, "serve"], check=False)

    deadline = time.monotonic() + DAEMON_START_TIMEOUT
    while time.monotonic() < deadline:
        if daemon_alive(sock_path):
            _print({"status": "started", "session": SESSION_NAME})
            return
        time.sleep(DAEMON_POLL_INTERVAL)
    _print({"error": f"daemon did not answer on {sock_path} within {DAEMON_START_TIMEOUT}s"})
    sys.exit(1)


def cmd_daemon_stop(args: argparse.Namespace) -> None:
    data_dir = pl.Path(args.data_dir or default_data_dir())
    sock_path = _sock_path(data_dir)

    if not daemon_alive(sock_path):
        _print({"status": "already_stopped", "session": SESSION_NAME})
        return

    # Drop the marker before signaling so the serve process's shutdown finds it and skips the
    # daemon_died notification; a crash never writes this marker, so it still gets reported.
    data_dir.mkdir(parents=True, exist_ok=True)
    _stop_marker_path(data_dir).write_text("")

    screen_bin = shutil.which("screen")
    if screen_bin is None:
        _print({"error": "screen is not on PATH"})
        sys.exit(1)
    subprocess.run([screen_bin, "-S", SESSION_NAME, "-X", "quit"], check=False)

    deadline = time.monotonic() + DAEMON_STOP_TIMEOUT
    while time.monotonic() < deadline:
        if not daemon_alive(sock_path):
            _print({"status": "stopped", "session": SESSION_NAME})
            return
        time.sleep(DAEMON_POLL_INTERVAL)
    _print({"error": f"daemon still answering after screen quit; inspect with 'screen -r {SESSION_NAME}'"})
    sys.exit(1)


def cmd_daemon_restart(args: argparse.Namespace) -> None:
    cmd_daemon_stop(args)
    cmd_daemon_start(args)


def cmd_daemon_status(args: argparse.Namespace) -> None:
    data_dir = pl.Path(args.data_dir or default_data_dir())
    sock_path = _sock_path(data_dir)

    status = asyncio.run(socket_request(sock_path, {"command": "status"})) if sock_path.exists() else {"error": "not running"}
    running = "error" not in status

    result: dict[str, object] = {"running": running, "session": SESSION_NAME}
    if running:
        result["port"] = status["port"]
        result["clients"] = status["clients"]
    _print(result)


def _log(message: str) -> None:
    print(f"[app-chat] {message}", file=sys.stderr, flush=True)
