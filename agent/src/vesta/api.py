"""Agent HTTP/WS server: core routes + skill auto-discovery.

The main aiohttp server exposes:
  - GET  /ws           internals event-bus monitor (CLI/admin, broad filter)
  - WS   /ws/chat  user ↔ LLM bidirectional chat channel
  - GET  /history      paginated chat event history
  - /<skill>/*         auto-mounted per-skill sub-apps from agent/skills/

The chat WS and history live in core because they're the LLM's
input/output pipe (coupled to message_queue + event_bus). Skills expose
feature-specific endpoints via /api/<name>/*.
"""

import asyncio
import importlib.util
import json
import pathlib
import sys

from aiohttp import web

import vesta.models as vm
from vesta import logger
from vesta.events import CHAT_TYPES, INTERNALS_TYPES, EventBus, HistoryEvent, VestaEvent


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


def _load_skill_server(skill_dir: pathlib.Path) -> object | None:
    """Load agent/skills/<name>/server.py as a package so its relative
    imports (e.g. `from .voice import routes`) work. Returns the loaded
    module or None if the skill has no server.py."""
    server_py = skill_dir / "server.py"
    if not server_py.exists():
        return None
    pkg_name = f"_skill_{skill_dir.name.replace('-', '_')}"
    if pkg_name in sys.modules:
        return sys.modules[pkg_name]
    spec = importlib.util.spec_from_file_location(
        pkg_name,
        server_py,
        submodule_search_locations=[str(skill_dir)],
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        logger.error(f"failed to load skill server at {skill_dir.name}: {e}")
        sys.modules.pop(pkg_name, None)
        return None
    return module


def _mount_skill_servers(app: web.Application, config: vm.VestaConfig) -> None:
    """Discover and mount every skill that exposes a server.py with a
    routes() function. Each skill's routes are mounted under a sub-app
    at /<skill_dir_name>/, so `skills/<name>/server.py` exposing
    `/ws` becomes reachable at `/<name>/ws`."""
    skills_dir = config.skills_dir
    if not skills_dir.exists():
        return
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        module = _load_skill_server(skill_dir)
        if module is None:
            continue
        routes_fn = getattr(module, "routes", None)
        if not callable(routes_fn):
            continue
        try:
            skill_routes = routes_fn()
        except Exception as e:
            logger.error(f"skill {skill_dir.name} routes() failed: {e}")
            continue
        sub_app = web.Application()
        # Share parent app state so skill handlers can reach event_bus,
        # message_queue, state, config just like the core handlers.
        sub_app["config"] = config
        sub_app["event_bus"] = app["event_bus"]
        sub_app["message_queue"] = app["message_queue"]
        sub_app["state"] = app["state"]
        sub_app.add_routes(skill_routes)
        app.add_subapp(f"/{skill_dir.name}/", sub_app)
        logger.startup(f"mounted skill '{skill_dir.name}' at /{skill_dir.name}/")


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
    _mount_skill_servers(app, config)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
