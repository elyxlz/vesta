"""App Chat daemon.

Connects to the agent's /ws endpoint. Writes notification files for inbound
user messages and accepts CLI commands via Unix socket to send replies.
"""

import asyncio
import datetime as dt
import json
import os
import pathlib as pl
import signal
import sys
import uuid
from dataclasses import dataclass, field

import aiohttp


RECONNECT_DELAY = 2.0


@dataclass
class DaemonState:
    notifications_dir: pl.Path
    ws_url: str
    sock_path: pl.Path
    shutdown: asyncio.Event = field(default_factory=asyncio.Event)
    ws: aiohttp.ClientWebSocketResponse | None = None
    session: aiohttp.ClientSession | None = None
    last_seen_ts: str | None = None


def cmd_serve(args: object) -> None:
    notifications_dir = pl.Path(args.notifications_dir)
    ws_url = args.ws_url
    data_dir = pl.Path(args.data_dir or pl.Path.home() / ".app-chat")

    notifications_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    sock_path = data_dir / "app-chat.sock"

    state = DaemonState(
        notifications_dir=notifications_dir,
        ws_url=ws_url,
        sock_path=sock_path,
    )
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
            async with state.session.ws_connect(state.ws_url) as ws:
                state.ws = ws
                _log(f"connected to {state.ws_url}")
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        _handle_event(state, msg.data)
                    elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                        break
        except (aiohttp.ClientError, OSError) as exc:
            _log(f"ws error: {exc}")
        finally:
            state.ws = None
        if not state.shutdown.is_set():
            await asyncio.sleep(RECONNECT_DELAY)


def _handle_event(state: DaemonState, raw: str) -> None:
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        _log(f"bad json from ws: {raw[:200]}")
        return
    if "type" not in event:
        return

    event_type = event["type"]

    if event_type == "history" and "events" in event:
        _replay_missed(state, event["events"])
        return

    if "ts" in event:
        state.last_seen_ts = event["ts"]

    if event_type == "user" and "text" in event:
        ts = event["ts"] if "ts" in event else None
        _write_notification(state, event["text"], timestamp=ts)


def _replay_missed(state: DaemonState, events: list[dict[str, object]]) -> None:
    """On reconnect, generate notifications for user messages missed during downtime."""
    cutoff = state.last_seen_ts
    count = 0
    for past in events:
        if "type" not in past or past["type"] != "user" or "text" not in past:
            continue
        ts = past["ts"] if "ts" in past else None
        if cutoff and ts and str(ts) <= cutoff:
            continue
        _write_notification(state, str(past["text"]), timestamp=str(ts) if ts else None)
        count += 1
    # Update last_seen_ts to the latest event in the batch
    for past in reversed(events):
        if "ts" in past:
            state.last_seen_ts = str(past["ts"])
            break
    if count:
        _log(f"replayed {count} missed message(s)")


def _write_notification(state: DaemonState, message: str, *, timestamp: str | None = None) -> None:
    if not message.strip():
        return
    ts = timestamp or dt.datetime.now(dt.UTC).isoformat()
    notification = {
        "timestamp": ts,
        "source": "app-chat",
        "type": "message",
        "message": message,
        "interrupt": True,
    }
    filename = f"{uuid.uuid4()}-app-chat-message.json"
    path = state.notifications_dir / filename
    path.write_text(json.dumps(notification), encoding="utf-8")
    _log(f"notification: {filename}")


async def _socket_server(state: DaemonState) -> None:
    state.sock_path.unlink(missing_ok=True)

    async def handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await _handle_socket_conn(state, reader, writer)

    server = await asyncio.start_unix_server(handle_conn, path=str(state.sock_path))
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
