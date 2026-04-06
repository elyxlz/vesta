"""Agent HTTP/WS server.

Routes:
  - WS   /ws              bidirectional event bus
  - GET  /history         paginated event history
  - GET  /services        list registered skill services
  - POST /services        register a skill service
  - DELETE /services/{n}  unregister a skill service
"""

import asyncio
import json

from aiohttp import web

from vesta.events import EventBus, HistoryEvent, VestaEvent
from vesta.config import VestaConfig
from vesta import services


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


async def _services_list(request: web.Request) -> web.Response:
    return web.json_response({"services": services.all_services()})


async def _services_register(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    name = data.get("name", "").strip()
    port = data.get("port")
    if not name or not isinstance(port, int):
        return web.json_response({"error": "name (str) and port (int) required"}, status=400)
    try:
        services.register(name, port)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"ok": True})


async def _services_unregister(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    services.unregister(name)
    return web.json_response({"ok": True})


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
    app.router.add_get("/services", _services_list)
    app.router.add_post("/services", _services_register)
    app.router.add_delete("/services/{name}", _services_unregister)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
