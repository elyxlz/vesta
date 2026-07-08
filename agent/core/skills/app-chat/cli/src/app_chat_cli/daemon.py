"""App Chat daemon.

Holds a kept-alive connection to the agent's /ws endpoint and accepts CLI commands via a Unix
socket to send replies (`app-chat send` -> a `chat` frame). Inbound app messages are turned into
notifications by the agent itself (core/api.py), not here — so a dead daemon can no longer silently
swallow intake; it only fails the reply path, and loudly ("not connected to agent")."""

import argparse
import asyncio
import functools
import json
import os
import pathlib as pl
import signal
import sys
from dataclasses import dataclass, field

import aiohttp


RECONNECT_DELAY = 2.0


@dataclass
class DaemonState:
    ws_url: str
    sock_path: pl.Path
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    ws: aiohttp.ClientWebSocketResponse | None = None
    session: aiohttp.ClientSession | None = None


def cmd_serve(args: argparse.Namespace) -> None:
    ws_url = args.ws_url
    data_dir = pl.Path(args.data_dir or pl.Path.home() / ".app-chat")
    data_dir.mkdir(parents=True, exist_ok=True)

    sock_path = data_dir / "app-chat.sock"

    state = DaemonState(ws_url=ws_url, sock_path=sock_path)
    asyncio.run(_run(state))


async def _run(state: DaemonState) -> None:
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, state.shutdown.set)

    state.session = aiohttp.ClientSession()
    try:
        tasks = [
            asyncio.create_task(_ws_loop(state)),
            asyncio.create_task(_socket_server(state)),
        ]
        await state.shutdown.wait()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    finally:
        await state.session.close()
        state.sock_path.unlink(missing_ok=True)


async def _ws_loop(state: DaemonState) -> None:
    while not state.shutdown.is_set():
        try:
            if state.session is None:
                break
            url = state.ws_url
            agent_token = os.environ.get("AGENT_TOKEN")
            if agent_token:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}agent_token={agent_token}"
            async with state.session.ws_connect(url) as ws:
                state.ws = ws
                _log(f"connected to {state.ws_url}")
                # Drain inbound frames only to keep the connection live and notice a close; the
                # agent owns intake now, so nothing here reacts to them.
                async for msg in ws:
                    if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break
        except (aiohttp.ClientError, OSError) as exc:
            _log(f"ws error: {exc}")
        finally:
            state.ws = None
        if not state.shutdown.is_set():
            await asyncio.sleep(RECONNECT_DELAY)


async def _socket_server(state: DaemonState) -> None:
    state.sock_path.unlink(missing_ok=True)

    server = await asyncio.start_unix_server(functools.partial(_handle_socket_conn, state), path=str(state.sock_path))
    os.chmod(str(state.sock_path), 0o600)
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
                response = {"error": "empty message"}
            elif state.ws and not state.ws.closed:
                await state.ws.send_json({"type": "chat", "text": message})
                response = {"ok": True, "message": message}
            else:
                response = {"error": "not connected to agent"}
        else:
            response = {"error": f"unknown command: {command}"}

        writer.write(json.dumps(response).encode())
        await writer.drain()
    except (json.JSONDecodeError, KeyError, TimeoutError, OSError) as exc:
        _log(f"socket error: {exc}")
    finally:
        writer.close()
        await writer.wait_closed()


def _log(message: str) -> None:
    print(f"[app-chat] {message}", file=sys.stderr, flush=True)
