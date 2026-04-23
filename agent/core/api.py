"""Agent HTTP/WS server.

Routes:
  - WS   /ws                   bidirectional event bus
  - GET  /history              paginated event history (cursor optional)
  - GET  /search               full-text search over events
  - GET  /usage                plan usage limits and rate limit status
  - GET  /memory               read MEMORY.md
  - PUT  /memory               overwrite MEMORY.md (applies on next restart)
"""

import asyncio
import json
import logging
import pathlib as pl

import aiohttp as _aiohttp
from aiohttp import web

from .events import ChatEvent, EventBus, HistoryEvent, UserEvent, VestaEvent
from .config import VestaConfig
from .helpers import get_memory_path

logger = logging.getLogger("vesta.api")


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Bidirectional event bus WebSocket.

    Send: all events from the event bus are pushed to connected clients.
    Recv: clients can emit events (e.g. user messages, chat replies).
    On connect: sends recent history unless ?skip_history=1 is passed."""
    event_bus: EventBus = request.app["event_bus"]
    skip_history = request.query.get("skip_history", "") in ("1", "true")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    sub = event_bus.subscribe()
    recv_task: asyncio.Task[None] | None = None
    send_task: asyncio.Task[None] | None = None
    try:
        if not skip_history:
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
            if "type" not in data:
                continue
            msg_type = data["type"]
            if msg_type in ("message", "chat"):
                if "text" not in data:
                    continue
                text = data["text"].strip()
                if text:
                    if msg_type == "message":
                        event: UserEvent = {"type": "user", "text": text}
                        if "input_method" in data and data["input_method"] in ("voice", "typed"):
                            event["input_method"] = data["input_method"]
                        event_bus.emit(event)
                    else:
                        event_bus.emit(ChatEvent(type="chat", text=text))
        elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
            break


async def _send_loop(ws: web.WebSocketResponse, sub: asyncio.Queue[VestaEvent]) -> None:
    """Forward all event-bus events to the WS client."""
    try:
        while True:
            event = await sub.get()
            await ws.send_json(event)
    except asyncio.CancelledError:
        pass
    except (ConnectionError, RuntimeError, TypeError) as e:
        logger.info(f"ws send_loop exited: {type(e).__name__}: {e}")


async def _history_handler(request: web.Request) -> web.Response:
    """Paginated event history.

    Query params:
      cursor (int, optional) — fetch events before this id. Omit for most recent.
      limit  (int, optional) — max events to return (default: EventBus.PAGE_SIZE).
    """
    event_bus: EventBus = request.app["event_bus"]

    limit_raw = request.query.get("limit", "")
    try:
        limit = int(limit_raw) if limit_raw else None
    except ValueError:
        return web.json_response({"error": "invalid limit"}, status=400)

    kwargs = {"limit": limit} if limit is not None else {}

    cursor_raw = request.query.get("cursor", "")
    if cursor_raw:
        try:
            cursor = int(cursor_raw)
        except ValueError:
            return web.json_response({"error": "invalid cursor"}, status=400)
        events, next_cursor = event_bus.before(cursor, **kwargs)
    else:
        events, next_cursor = event_bus.recent(**kwargs)

    return web.json_response({"events": events, "cursor": next_cursor})


async def _search_handler(request: web.Request) -> web.Response:
    """Full-text search over events.

    Query params:
      q     (str, required)  — FTS5 search query.
      limit (int, optional)  — max results (default: 20).
    """
    event_bus: EventBus = request.app["event_bus"]
    query = request.query.get("q", "").strip()
    if not query:
        return web.json_response({"error": "missing 'q' param"}, status=400)
    limit_raw = request.query.get("limit", "")
    try:
        limit = int(limit_raw) if limit_raw else 20
    except ValueError:
        return web.json_response({"error": "invalid limit"}, status=400)
    try:
        results = event_bus.search(query, limit=limit)
    except Exception:
        return web.json_response({"error": "invalid search query"}, status=400)
    return web.json_response({"results": results})


CREDENTIALS_PATH = pl.Path.home() / ".claude" / ".credentials.json"
ANTHROPIC_API_URL = "https://api.anthropic.com"
OAUTH_BETA_HEADER = "oauth-2025-04-20"


def _read_oauth_token() -> str | None:
    try:
        data = json.loads(CREDENTIALS_PATH.read_text())
        return data["claudeAiOauth"]["accessToken"]
    except (OSError, KeyError, json.JSONDecodeError):
        return None


async def _usage_handler(request: web.Request) -> web.Response:
    """Proxy plan usage limits from Anthropic API."""
    token = _read_oauth_token()
    if not token:
        return web.json_response({"error": "no oauth credentials"}, status=503)

    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": OAUTH_BETA_HEADER,
        "Content-Type": "application/json",
        "User-Agent": "claude-code/2.1.92",
    }
    try:
        async with _aiohttp.ClientSession() as session:
            async with session.get(
                f"{ANTHROPIC_API_URL}/api/oauth/usage",
                headers=headers,
                timeout=_aiohttp.ClientTimeout(total=10),
            ) as resp:
                body = await resp.json()
                if resp.status != 200:
                    return web.json_response({"error": f"anthropic returned {resp.status}", "body": body}, status=resp.status)
                return web.json_response(body)
    except (TimeoutError, _aiohttp.ClientError) as e:
        logger.error(f"usage fetch failed: {e}")
        return web.json_response({"error": str(e)}, status=502)


async def _memory_get_handler(request: web.Request) -> web.Response:
    """Return current contents of MEMORY.md."""
    config: VestaConfig = request.app["config"]
    path = get_memory_path(config)
    if not path.exists():
        return web.json_response({"error": "MEMORY.md not found"}, status=404)
    return web.json_response({"content": path.read_text()})


async def _memory_put_handler(request: web.Request) -> web.Response:
    """Overwrite MEMORY.md. Takes effect after agent restart."""
    config: VestaConfig = request.app["config"]
    try:
        data = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    if "content" not in data or not isinstance(data["content"], str):
        return web.json_response({"error": "body must be {content: string}"}, status=400)
    path = get_memory_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data["content"])
    return web.json_response({"ok": True})


@web.middleware
async def _auth_middleware(request: web.Request, handler):
    expected = request.app.get("agent_token")
    if expected is None:
        return await handler(request)
    token = request.headers.get("X-Agent-Token") or request.query.get("agent_token")
    if token != expected:
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def start_ws_server(
    event_bus: EventBus,
    config: VestaConfig,
    *,
    host: str = "0.0.0.0",
) -> web.AppRunner:
    app = web.Application(middlewares=[_auth_middleware])
    app["event_bus"] = event_bus
    app["agent_token"] = config.agent_token
    app["config"] = config
    app.router.add_get("/ws", _ws_handler)
    app.router.add_get("/history", _history_handler)
    app.router.add_get("/search", _search_handler)
    app.router.add_get("/usage", _usage_handler)
    app.router.add_get("/memory", _memory_get_handler)
    app.router.add_put("/memory", _memory_put_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, config.ws_port)
    await site.start()
    return runner
