"""Agent HTTP/WS server: core routes + skill server proxy.

The main aiohttp server exposes:
  - WS   /ws          bidirectional event bus (all event types, clients filter)
  - GET  /history     paginated event history
  - /{skill}/*        reverse-proxied to skill HTTP servers (see skill_server.py)

When a skill runs its own HTTP server, append one tuple to SKILL_SERVERS in
skill_server.py: (SKILL_NAME, PORT). The proxy strips the /{skill_name}
prefix and forwards to localhost:{port}.
"""

import asyncio
import json

from aiohttp import web

from vesta.events import EventBus, HistoryEvent, VestaEvent
from vesta.config import VestaConfig
from vesta.skill_server import wire_skill_proxies


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Bidirectional event bus WebSocket.

    Send: all events from the event bus are pushed to connected clients.
    Recv: clients can emit events (e.g. user messages, chat replies).
    On connect: sends recent history."""
    event_bus: EventBus = request.app["event_bus"]

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    sub = event_bus.subscribe()
    recv_task: asyncio.Task[None] | None = None
    send_task: asyncio.Task[None] | None = None
    try:
        events, cursor = event_bus.recent()
        if events:
            await ws.send_json(HistoryEvent(type="history", events=events, state=event_bus.state, cursor=cursor))
        recv_task = asyncio.create_task(_recv_loop(ws, event_bus))
        send_task = asyncio.create_task(_send_loop(ws, sub))
        await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        recv_task and recv_task.cancel()
        send_task and send_task.cancel()
        await asyncio.gather(recv_task, send_task, return_exceptions=True)
        event_bus.unsubscribe(sub)

    return ws


async def _recv_loop(ws: web.WebSocketResponse, event_bus: EventBus) -> None:
    """Receive events from clients and emit to event bus."""
    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except (json.JSONDecodeError, TypeError):
                continue
            msg_type = data.get("type")
            if msg_type == "message":
                text = data.get("text", "").strip()
                if text:
                    event_bus.emit({"type": "user", "text": text})
            elif msg_type == "chat":
                text = data.get("text", "").strip()
                if text:
                    event_bus.emit({"type": "chat", "text": text})
        elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
            break


async def _send_loop(ws: web.WebSocketResponse, sub: asyncio.Queue[VestaEvent]) -> None:
    """Forward all event-bus events to the WS client."""
    try:
        while True:
            event = await sub.get()
            await ws.send_json(event)
    except (ConnectionError, RuntimeError, TypeError, asyncio.CancelledError):
        pass


async def _history_handler(request: web.Request) -> web.Response:
    event_bus: EventBus = request.app["event_bus"]
    cursor_raw = request.query.get("cursor", "")
    if not cursor_raw:
        return web.json_response({"error": "missing 'cursor' param"}, status=400)
    try:
        cursor = int(cursor_raw)
    except ValueError:
        return web.json_response({"error": "invalid cursor"}, status=400)
    events, next_cursor = event_bus.before(cursor)
    return web.json_response({"events": events, "cursor": next_cursor})


async def start_ws_server(
    event_bus: EventBus,
    config: VestaConfig,
    *,
    host: str = "0.0.0.0",
) -> web.AppRunner:
    app = web.Application()
    app["event_bus"] = event_bus
    app.router.add_get("/ws", _ws_handler)
    app.router.add_get("/history", _history_handler)

    # Skill server proxies (catch-all — must be registered after core routes)
    wire_skill_proxies(app)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
