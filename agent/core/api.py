"""Agent HTTP/WS server.

Routes:
  - WS   /ws                   bidirectional event bus
  - GET  /history              paginated event history (cursor optional)
  - GET  /search               full-text search over events
  - GET  /usage                plan usage limits and rate limit status
  - GET  /provider/status      LLM-provider auth state
  - POST /provider             set Claude credentials or OpenRouter config
  - GET  /memory               read MEMORY.md
  - PUT  /memory               overwrite MEMORY.md (applies on next restart)
"""

import asyncio
import json
import logging
import sqlite3
import weakref

import aiohttp as _aiohttp
from aiohttp import web

from .events import ChatEvent, EventBus, HistoryEvent, UserEvent, VestaEvent
from .config import VestaConfig
from .helpers import get_memory_path
from .models import State
from .provider import CREDENTIALS_PATH, set_claude, set_model, set_openrouter


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
    request.app["websockets"].add(ws)

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
        if recv_task:
            recv_task.cancel()
        if send_task:
            send_task.cancel()
        await asyncio.gather(recv_task, send_task, return_exceptions=True)
        event_bus.unsubscribe(sub)
        request.app["websockets"].discard(ws)

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
                if "text" not in data or not isinstance(data["text"], str):
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
    except sqlite3.OperationalError:
        # FTS5 raises OperationalError for a malformed MATCH expression: that's a client error.
        return web.json_response({"error": "invalid search query"}, status=400)
    except sqlite3.Error as e:
        # A genuine SQLite fault (locked db, disk full, corrupted FTS) must surface, not masquerade as a bad query.
        logger.error(f"search failed for query={query!r}: {e}")
        return web.json_response({"error": "search failed"}, status=500)
    return web.json_response({"results": results})


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
                if resp.status != 200:
                    # Read as text first: an upstream error body may not be JSON, and resp.json() would
                    # raise ContentTypeError, masking the real status behind a generic 502.
                    body = await resp.text()
                    return web.json_response({"error": f"anthropic returned {resp.status}", "body": body}, status=resp.status)
                return web.json_response(await resp.json())
    except (TimeoutError, _aiohttp.ClientError) as e:
        logger.error(f"usage fetch failed: {e}")
        return web.json_response({"error": str(e)}, status=502)


async def _provider_status_handler(request: web.Request) -> web.Response:
    """Report the agent's LLM-provider authentication state.

    Read by vestad on every status poll to surface 'alive' vs 'not_authenticated'
    to the web UI. Agent is the source of truth — vestad knows nothing about
    credential file formats."""
    state = request.app["state"]
    if state.provider_status is None:
        return web.json_response({"error": "provider not initialized"}, status=503)
    status = state.provider_status
    return web.json_response(
        {
            "state": status.state.value,
            "kind": status.kind,
            "model": status.model,
            # vestad gates "alive" on this: an authenticated agent that hasn't yet
            # finished first-start setup (or whose first model call failed) is not ready.
            "setup_complete": state.persisted.first_start_done,
        }
    )


async def _provider_set_handler(request: web.Request) -> web.Response:
    """Apply new provider config. Mutually exclusive body shapes:
    - `{credentials, model?}`            -> set Claude (OAuth blob, optional model)
    - `{openrouter_key, openrouter_model}` -> set OpenRouter (switch / refresh key)
    - `{model}`                          -> change model only, keep current provider
    Vestad orchestrates the container restart that picks up env-var changes."""
    state = request.app["state"]
    config: VestaConfig = request.app["config"]
    if state.provider_status is None:
        return web.json_response({"error": "provider not initialized"}, status=503)
    try:
        data = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)

    has_creds = "credentials" in data and isinstance(data["credentials"], str)
    has_or = "openrouter_key" in data and isinstance(data["openrouter_key"], str)
    has_model = "model" in data and isinstance(data["model"], str)
    if has_creds and has_or:
        return web.json_response({"error": "credentials and openrouter_key are mutually exclusive"}, status=400)
    if not has_creds and not has_or and not has_model:
        return web.json_response({"error": "must provide credentials, openrouter_key, or model"}, status=400)

    if has_creds:
        claude_model = data["model"] if has_model else None
        try:
            state.provider_status = set_claude(data["credentials"], claude_model, config=config, persisted=state.persisted)
        except (json.JSONDecodeError, TypeError) as e:
            return web.json_response({"error": f"invalid credentials: {e}"}, status=400)
        except OSError as e:
            return web.json_response({"error": f"set_claude failed: {e}"}, status=500)
    elif has_or:
        if "openrouter_model" not in data or not isinstance(data["openrouter_model"], str):
            return web.json_response({"error": "openrouter_model is required when openrouter_key is set"}, status=400)
        try:
            state.provider_status = set_openrouter(data["openrouter_key"], data["openrouter_model"], config=config, persisted=state.persisted)
        except OSError as e:
            return web.json_response({"error": f"set_openrouter failed: {e}"}, status=500)
    else:
        # Model-only change: keep the current provider and any stored key.
        try:
            state.provider_status = set_model(data["model"], config=config, persisted=state.persisted)
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)
        except OSError as e:
            return web.json_response({"error": f"set_model failed: {e}"}, status=500)

    return web.json_response({"ok": True})


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
    expected = request.app["agent_token"]
    if expected is None:
        return await handler(request)
    token = request.headers.get("X-Agent-Token") or request.query.get("agent_token")
    if token != expected:
        return web.json_response({"error": "unauthorized"}, status=401)
    return await handler(request)


async def start_runner(app: web.Application, *, shutdown_timeout: float = 5.0) -> web.AppRunner:
    """Set up and return an aiohttp AppRunner. Caller starts a TCPSite/SockSite on it."""
    runner = web.AppRunner(app, shutdown_timeout=shutdown_timeout)
    await runner.setup()
    return runner


async def start_ws_server(
    event_bus: EventBus,
    config: VestaConfig,
    state: State | None = None,
    *,
    host: str = "0.0.0.0",
) -> web.AppRunner:
    app = web.Application(middlewares=[_auth_middleware])
    app["event_bus"] = event_bus
    app["agent_token"] = config.agent_token
    app["config"] = config
    app["state"] = state
    app["websockets"] = weakref.WeakSet()
    app.on_shutdown.append(_close_all_websockets)
    app.router.add_get("/ws", _ws_handler)
    app.router.add_get("/history", _history_handler)
    app.router.add_get("/search", _search_handler)
    app.router.add_get("/usage", _usage_handler)
    app.router.add_get("/provider/status", _provider_status_handler)
    app.router.add_post("/provider", _provider_set_handler)
    app.router.add_get("/memory", _memory_get_handler)
    app.router.add_put("/memory", _memory_put_handler)

    runner = await start_runner(app)
    await web.TCPSite(runner, host, config.ws_port).start()
    return runner


async def _close_all_websockets(app: web.Application) -> None:
    sockets = list(app["websockets"])
    if not sockets:
        return
    await asyncio.gather(
        *(ws.close(code=_aiohttp.WSCloseCode.GOING_AWAY, message=b"server shutdown") for ws in sockets),
        return_exceptions=True,
    )
