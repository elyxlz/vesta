"""Agent HTTP/WS server: core routes + skill endpoints.

The main aiohttp server exposes:
  - GET  /ws           internals event-bus monitor (CLI/admin, broad filter)
  - WS   /ws/chat      user ↔ LLM bidirectional chat channel
  - GET  /history      paginated chat event history
  - skill endpoints listed in SKILL_ENDPOINTS (one row per exposed function)

When a skill exposes HTTP functions, append one tuple per endpoint to
SKILL_ENDPOINTS below: (METHOD, PATH, "module.path:func_name"). The skill's
package is imported from config.skills_dir at startup.
"""

import asyncio
import importlib
import json
import sys

from aiohttp import web

import vesta.models as vm
from vesta import logger
from vesta.events import CHAT_TYPES, INTERNALS_TYPES, EventBus, HistoryEvent, VestaEvent

# Skill HTTP endpoints. Append one row per function a skill wants reachable
# over HTTP. Format: (METHOD, PATH, "module:function"). Module is resolved
# against config.skills_dir (added to sys.path at startup). WebSocket
# handlers register as GET. Rows that fail to import are logged and skipped.
SKILL_ENDPOINTS: list[tuple[str, str, str]] = []


async def ws_handler(request: web.Request, channel: str, filter_types: frozenset[str]) -> web.WebSocketResponse:
    """Shared WS pump used by the internals channel and the chat skill.
    Subscribes to the event bus, sends history on open, pumps recv + send loops."""
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
        history_log = event_bus.log(channel)
        if history_log:
            events, cursor = history_log.recent()
            if events:
                await ws.send_json(HistoryEvent(type="history", events=events, state=event_bus.state, cursor=cursor))
        recv_task = asyncio.create_task(recv_loop(ws, message_queue, state, config))
        send_task = asyncio.create_task(send_loop(ws, sub, filter_types))
        await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        recv_task and recv_task.cancel()
        send_task and send_task.cancel()
        await asyncio.gather(recv_task, send_task, return_exceptions=True)
        event_bus.unsubscribe(sub)

    return ws


async def recv_loop(
    ws: web.WebSocketResponse,
    message_queue: asyncio.Queue[tuple[str, bool]],
    state: vm.State,
    config: vm.VestaConfig,
) -> None:
    """Parse incoming WS messages and route them to the message queue or
    the interrupt mechanism. Message types: `message`, `system_message`,
    `interrupt`."""
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
            elif msg_type == "system_message":
                text = data.get("text", "").strip()
                if text:
                    await message_queue.put((text, False))
            elif msg_type == "interrupt":
                from vesta.core.client import attempt_interrupt

                await attempt_interrupt(state, config=config, reason="WS interrupt")
        elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
            break


async def send_loop(ws: web.WebSocketResponse, sub: asyncio.Queue[VestaEvent], filter_types: frozenset[str]) -> None:
    """Forward event-bus events matching the channel's filter to the WS client."""
    try:
        while True:
            event = await sub.get()
            if event["type"] in filter_types:
                await ws.send_json(event)
    except (ConnectionError, RuntimeError, TypeError, asyncio.CancelledError):
        pass


async def _internals_handler(request: web.Request) -> web.WebSocketResponse:
    return await ws_handler(request, "internals", INTERNALS_TYPES)


async def _chat_handler(request: web.Request) -> web.WebSocketResponse:
    return await ws_handler(request, "chat", CHAT_TYPES)


async def _history_handler(request: web.Request) -> web.Response:
    event_bus: EventBus = request.app["event_bus"]
    cursor_raw = request.query.get("cursor", "")
    if not cursor_raw:
        return web.json_response({"error": "missing 'cursor' param"}, status=400)
    try:
        cursor = int(cursor_raw)
    except ValueError:
        return web.json_response({"error": "invalid cursor"}, status=400)
    history_log = event_bus.log("chat")
    if not history_log:
        return web.json_response({"events": [], "cursor": None})
    events, next_cursor = history_log.before(cursor)
    return web.json_response({"events": events, "cursor": next_cursor})


def _wire_skill_endpoints(app: web.Application, config: vm.VestaConfig) -> None:
    """Register every row in SKILL_ENDPOINTS. Adds config.skills_dir to
    sys.path so each skill dir becomes a top-level importable package.
    Rows that fail to import/resolve are logged and skipped — one broken
    skill cannot prevent the server from starting."""
    skills_dir = str(config.skills_dir)
    if skills_dir not in sys.path:
        sys.path.insert(0, skills_dir)
    for method, path, target in SKILL_ENDPOINTS:
        try:
            module_name, func_name = target.split(":", 1)
        except ValueError:
            logger.error(f"skill endpoint {method} {path}: bad target '{target}' (expected 'module:func')")
            continue
        try:
            module = importlib.import_module(module_name)
            handler = getattr(module, func_name)
        except Exception as e:
            logger.error(f"skill endpoint {method} {path} -> {target} failed to load: {e}")
            continue
        app.router.add_route(method, path, handler)
        logger.startup(f"wired skill endpoint {method} {path} -> {target}")


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
    app.router.add_get("/ws/chat", _chat_handler)
    app.router.add_get("/history", _history_handler)

    _wire_skill_endpoints(app, config)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
