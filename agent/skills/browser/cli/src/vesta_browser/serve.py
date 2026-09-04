"""The browser daemon: one unix socket, one JSON line per request, one owner for every browser decision.

`browser daemon start` runs `browser serve` detached; nothing else launches this. Handlers return a
`protocol.Result`, and a `BrowserError` raised anywhere inside a handler becomes the failed result
for that request alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import pathlib as pl
import signal
import socket
import sys
import time
import typing as tp

from . import protocol as p
from .daemon_state import State, routes
from .runtime_paths import Paths, load_paths

logger = logging.getLogger(__name__)
IDLE_SWEEP_SECS = 60
CLIENT_TIMEOUT_SECS = 5.0


def _invalid(message: str) -> p.Error:
    return p.error("invalid_request", "validation", message, retryable=False, suggested_action="fix the request and retry")


async def op_status(state: State, request_id: str) -> p.Result:
    data: p.JsonValue = {"protocol_version": p.PROTOCOL_VERSION, "pid": os.getpid(), "socket": str(state.paths.socket)}
    return p.result(request_id=request_id, op="status", ok=True, data=data)


async def op_engines(state: State, request_id: str) -> p.Result:
    return p.result(request_id=request_id, op="engines", ok=True, data=routes(state.paths))


Handler = tp.Callable[[State, dict[str, p.JsonValue]], tp.Awaitable[p.Result]]


async def handle_request(state: State, request: dict[str, p.JsonValue]) -> p.Result:
    request_id = str(request["request_id"]) if "request_id" in request else ""
    op = str(request["op"]) if "op" in request else ""
    try:
        if "version" not in request or request["version"] != p.PROTOCOL_VERSION:
            raise p.BrowserError(_invalid(f"unsupported protocol version; this daemon speaks {p.PROTOCOL_VERSION}"))
        if op not in HANDLERS:
            raise p.BrowserError(_invalid(f"unknown op {op!r}"))
        return await HANDLERS[op](state, request)
    except p.BrowserError as exc:
        state.last_error = exc.err
        return p.result(request_id=request_id, op=op, ok=False, err=exc.err)


async def _handle_connection(state: State, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        line = await reader.readline()
    except asyncio.LimitOverrunError:
        line = b""
    try:
        request = json.loads(line) if line else {}
        if not isinstance(request, dict):
            raise ValueError("request must be an object")
        response = await handle_request(state, request)
    except ValueError as exc:
        response = p.result(request_id="", op="", ok=False, err=_invalid(f"unreadable request: {exc}"))
    writer.write((json.dumps(response) + "\n").encode())
    with contextlib.suppress(ConnectionError):
        await writer.drain()
    writer.close()


def _write_daemon_died(paths: Paths, reason: str) -> None:
    paths.notifications.mkdir(exist_ok=True)
    notif = {"source": "browser", "type": "daemon_died", "reason": reason, "timestamp": p.now_iso()}
    filename = f"{int(time.time() * 1e6)}-browser-daemon_died.json"
    tmp = paths.notifications / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif))
    tmp.replace(paths.notifications / filename)


async def serve(paths: Paths) -> int:
    state = State(paths=paths)
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.socket.unlink(missing_ok=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def on_signal(signum: int) -> None:
        state.asked_to_stop = signum == signal.SIGTERM
        stop.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, on_signal, signum)
    old_umask = os.umask(0o177)
    try:
        server = await asyncio.start_unix_server(
            lambda r, w: _handle_connection(state, r, w), path=str(paths.socket), limit=p.REQUEST_MAX_BYTES
        )
    finally:
        os.umask(old_umask)
    logger.info("browser daemon listening on %s", paths.socket)
    try:
        await stop.wait()
    finally:
        server.close()
        await server.wait_closed()
        await shutdown(state)
        paths.socket.unlink(missing_ok=True)
        if not state.asked_to_stop:
            _write_daemon_died(paths, "signal")
    return 0


async def shutdown(state: State) -> None:
    """Stops every session; Task 9 fills this in. The skeleton has nothing to stop."""
    for task in list(state.tasks):
        task.cancel()
    for task in list(state.tasks):
        with contextlib.suppress(asyncio.CancelledError):
            await task


def ping(paths: Paths, timeout: float) -> bool:
    """Sync liveness probe: a daemon that answers `status` is up. Used by lifecycle readiness and the CLI."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(paths.socket))
            sock.sendall(json.dumps({"version": p.PROTOCOL_VERSION, "op": "status", "request_id": "ping"}).encode() + b"\n")
            data = b""
            while not data.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    break
                data += chunk
        return bool(data) and json.loads(data)["ok"] is True
    except (OSError, ValueError, KeyError):
        return False


async def request(paths: Paths, payload: dict[str, p.JsonValue]) -> p.Result:
    reader, writer = await asyncio.open_unix_connection(str(paths.socket), limit=p.REQUEST_MAX_BYTES * 4)
    writer.write((json.dumps(payload) + "\n").encode())
    await writer.drain()
    line = await reader.readline()
    writer.close()
    return json.loads(line)


HANDLERS: dict[str, Handler] = {
    "status": lambda state, req: op_status(state, str(req["request_id"])),
    "engines": lambda state, req: op_engines(state, str(req["request_id"])),
}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    return asyncio.run(serve(load_paths(os.environ, pl.Path.home())))
