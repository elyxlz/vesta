"""WebSocket API server for agent <-> app communication."""

import asyncio
import json

from aiohttp import web

import vesta.models as vm
from vesta import logger
from vesta.events import APP_CHAT_TYPES, INTERNALS_TYPES, EventBus, HistoryEvent, VestaEvent


async def _ws_handler(request: web.Request, filter_types: frozenset[str]) -> web.WebSocketResponse:
    event_bus: EventBus = request.app["event_bus"]
    message_queue: asyncio.Queue[tuple[str, bool]] = request.app["message_queue"]
    state: vm.State = request.app["state"]
    config: vm.VestaConfig = request.app["config"]

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    sub = event_bus.subscribe()
    recv_task: asyncio.Task[None] | None = None
    send_task: asyncio.Task[None] | None = None
    try:
        if event_bus.history:
            filtered = [e for e in event_bus.history if e["type"] in filter_types]
            if filtered:
                await ws.send_json(HistoryEvent(type="history", events=filtered, state=event_bus.state))
        recv_task = asyncio.create_task(_recv_loop(ws, message_queue, state, config))
        send_task = asyncio.create_task(_send_loop(ws, sub, filter_types))
        await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        recv_task and recv_task.cancel()
        send_task and send_task.cancel()
        await asyncio.gather(recv_task, send_task, return_exceptions=True)
        event_bus.unsubscribe(sub)

    return ws


async def _internals_handler(request: web.Request) -> web.WebSocketResponse:
    return await _ws_handler(request, INTERNALS_TYPES)


async def _app_chat_handler(request: web.Request) -> web.WebSocketResponse:
    return await _ws_handler(request, APP_CHAT_TYPES)


async def _recv_loop(
    ws: web.WebSocketResponse,
    message_queue: asyncio.Queue[tuple[str, bool]],
    state: vm.State,
    config: vm.VestaConfig,
) -> None:
    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"WS bad message: {e}")
                continue
            try:
                msg_type = data["type"]
            except KeyError:
                continue
            if msg_type == "message":
                text = data["text"].strip()
                if text:
                    await message_queue.put((text, True))
            elif msg_type == "interrupt":
                from vesta.core.client import attempt_interrupt

                await attempt_interrupt(state, config=config, reason="WS interrupt")
        elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
            break


async def _send_loop(ws: web.WebSocketResponse, sub: asyncio.Queue[VestaEvent], filter_types: frozenset[str]) -> None:
    try:
        while True:
            event = await sub.get()
            if event["type"] in filter_types:
                await ws.send_json(event)
    except (ConnectionError, RuntimeError, TypeError, asyncio.CancelledError):
        pass


async def start_ws_server(
    event_bus: EventBus,
    message_queue: asyncio.Queue[tuple[str, bool]],
    state: vm.State,
    config: vm.VestaConfig,
    *,
    host: str = "0.0.0.0",
) -> web.AppRunner:
    app = web.Application()
    app["event_bus"] = event_bus
    app["message_queue"] = message_queue
    app["state"] = state
    app["config"] = config
    app.router.add_get("/ws", _internals_handler)
    app.router.add_get("/ws/app-chat", _app_chat_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
