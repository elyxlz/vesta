"""WebSocket API server for agent ↔ app communication."""

import asyncio
import json

from aiohttp import web

import vesta.models as vm
from vesta import logger
from vesta.events import EventBus, HistoryEvent, VestaEvent


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    event_bus: EventBus = request.app["event_bus"]
    message_queue: asyncio.Queue[tuple[str, bool, list[str]]] = request.app["message_queue"]
    state: vm.State = request.app["state"]
    config: vm.VestaConfig = request.app["config"]

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    sub = event_bus.subscribe()
    recv_task: asyncio.Task[None] | None = None
    send_task: asyncio.Task[None] | None = None
    try:
        if event_bus.history:
            await ws.send_json(HistoryEvent(type="history", events=list(event_bus.history), state=event_bus.state))
        recv_task = asyncio.create_task(_recv_loop(ws, message_queue, state, config))
        send_task = asyncio.create_task(_send_loop(ws, sub))
        await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        if recv_task:
            recv_task.cancel()
        if send_task:
            send_task.cancel()
        event_bus.unsubscribe(sub)

    return ws


async def _recv_loop(
    ws: web.WebSocketResponse,
    message_queue: asyncio.Queue[tuple[str, bool, list[str]]],
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
                    await message_queue.put((text, True, []))
            elif msg_type == "interrupt":
                from vesta.core.client import attempt_interrupt

                await attempt_interrupt(state, config=config, reason="WS interrupt")
        elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
            break


async def _send_loop(ws: web.WebSocketResponse, sub: asyncio.Queue[VestaEvent]) -> None:
    try:
        while True:
            event = await sub.get()
            await ws.send_json(event)
    except (ConnectionError, RuntimeError, TypeError, asyncio.CancelledError):
        pass


async def start_ws_server(
    event_bus: EventBus,
    message_queue: asyncio.Queue[tuple[str, bool, list[str]]],
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
    app.router.add_get("/ws", _ws_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
