"""Agent HTTP/WS server.

Routes:
  - WS   /ws                   bidirectional event bus
  - GET  /history              paginated event history (cursor optional)
  - GET  /search               full-text search over events
  - GET  /provider/usage       normalized, provider-agnostic plan usage
  - GET  /config               full live config + derived {authed, kind, setup_complete}
  - PUT  /config               update preferences (model, context, thinking, personality, timezone, ...)
  - PUT  /config/auth          sign in: set Claude/OpenRouter credentials
  - DELETE /config/auth        sign out: clear credentials, leaving not_authenticated
  Writes don't restart; the caller applies them with one restart afterwards.
  - GET  /memory               read MEMORY.md
  - PUT  /memory               overwrite MEMORY.md (applies on next restart)
"""

import asyncio
import dataclasses as dc
import json
import logging
import sqlite3
import weakref

import aiohttp as _aiohttp
import pydantic as pyd
from aiohttp import web

from .events import ChatEvent, EventBus, HistoryEvent, UserEvent, VestaEvent
from .config import VestaConfig, update_config_store, validate_config_updates
from .helpers import get_memory_path
from .models import State
from .provider import ProviderAuthState, UsageError, clear_provider, get_usage, set_claude, set_openrouter


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
            # The chat WS is the app-chat surface, so seed it with the app-chat channel:
            # notifications/internal events still arrive on the live stream but never bury
            # the conversation in the capped recent window. Always send the history event,
            # even with no events, so the client can tell "still loading" from "no messages".
            # Run the read off the loop: a slow scan on a large db must not freeze the agent
            # (it would starve vestad's GET /config status poll and flap the agent to "starting").
            events, cursor = await asyncio.to_thread(event_bus.recent, channel="app-chat")
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
      cursor  (int, optional): fetch events before this id. Omit for most recent.
      limit   (int, optional): max events to return (default: EventBus.PAGE_SIZE).
      channel (str, optional): "app-chat" filters to the conversation event types.
    """
    event_bus: EventBus = request.app["event_bus"]

    limit_raw = request.query.get("limit", "")
    try:
        limit = int(limit_raw) if limit_raw else None
    except ValueError:
        return web.json_response({"error": "invalid limit"}, status=400)

    kwargs = {"limit": limit} if limit is not None else {}
    channel = request.query.get("channel", "") or None

    cursor_raw = request.query.get("cursor", "")
    if cursor_raw:
        try:
            cursor = int(cursor_raw)
        except ValueError:
            return web.json_response({"error": "invalid cursor"}, status=400)
        events, next_cursor = await asyncio.to_thread(event_bus.before, cursor, channel=channel, **kwargs)
    else:
        events, next_cursor = await asyncio.to_thread(event_bus.recent, channel=channel, **kwargs)

    return web.json_response({"events": events, "cursor": next_cursor})


async def _search_handler(request: web.Request) -> web.Response:
    """Full-text search over events.

    Query params:
      q     (str, required): FTS5 search query.
      limit (int, optional): max results (default: 20).
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
    except sqlite3.OperationalError as e:
        # FTS5 raises OperationalError for a malformed MATCH expression: that's a client error.
        logger.warning(f"search query rejected: {e}")
        return web.json_response({"error": "invalid search query"}, status=400)
    except sqlite3.Error as e:
        # A genuine SQLite fault (locked db, disk full, corrupted FTS) must surface, not masquerade as a bad query.
        logger.error(f"search failed for query={query!r}: {e}")
        return web.json_response({"error": "search failed"}, status=500)
    return web.json_response({"results": results})


async def _provider_usage_handler(request: web.Request) -> web.Response:
    """Report normalized, provider-agnostic plan usage for the agent's active provider."""
    config = request.app["config"]
    try:
        usage = await get_usage(config)
    except UsageError as e:
        logger.error(f"usage fetch failed: {e}")
        return web.json_response({"error": str(e)}, status=502)
    return web.json_response(dc.asdict(usage))


class _ProviderUpdate(pyd.BaseModel):
    """The `auth` sub-object of a PUT /config body: exactly one of `{credentials}` (Claude) or
    `{openrouter_key, openrouter_model}` (OpenRouter)."""

    model_config = pyd.ConfigDict(extra="forbid")

    credentials: str | None = None
    openrouter_key: str | None = None
    openrouter_model: str | None = None

    @pyd.model_validator(mode="after")
    def _exactly_one_provider(self) -> "_ProviderUpdate":
        if (self.credentials is None) == (self.openrouter_key is None):
            raise ValueError("provide exactly one of credentials or openrouter_key")
        if self.openrouter_key is not None and not self.openrouter_model:
            raise ValueError("openrouter_model is required with openrouter_key")
        return self


async def _config_auth_put_handler(request: web.Request) -> web.Response:
    """Sign in: set provider credentials (`{credentials}` for Claude, `{openrouter_key,
    openrouter_model}` for OpenRouter). Writes the credential files + config store; the change is
    applied by the next restart (callers write, then restart once)."""
    state: State = request.app["state"]
    config: VestaConfig = request.app["config"]
    if state.provider_status is None:
        return web.json_response({"error": "provider not initialized"}, status=503)
    try:
        update = _ProviderUpdate.model_validate(await request.json())
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    except pyd.ValidationError as e:
        return web.json_response({"error": f"invalid auth: {e.errors(include_url=False)}"}, status=400)
    try:
        if update.credentials is not None:
            state.provider_status = set_claude(update.credentials, config=config)
        elif update.openrouter_key is not None and update.openrouter_model is not None:
            state.provider_status = set_openrouter(update.openrouter_key, update.openrouter_model, config=config)
    except (json.JSONDecodeError, TypeError) as e:
        return web.json_response({"error": f"invalid credentials: {e}"}, status=400)
    except OSError as e:
        return web.json_response({"error": f"auth write failed: {e}"}, status=500)
    return web.json_response({"ok": True})


async def _config_auth_delete_handler(request: web.Request) -> web.Response:
    """Sign out: clear the provider credentials, leaving the agent not_authenticated. Idempotent.
    Applied by the next restart."""
    state: State = request.app["state"]
    config: VestaConfig = request.app["config"]
    try:
        state.provider_status = clear_provider(config=config)
    except OSError as e:
        return web.json_response({"error": f"clear_provider failed: {e}"}, status=500)
    return web.json_response({"ok": True})


async def _config_get_handler(request: web.Request) -> web.Response:
    """The full live config (every key, secrets redacted by SecretStr) plus the derived provider state
    the client needs to render settings: `authed`, `kind`, and `setup_complete`. Model and context are
    plain config fields here, so there's one read surface for everything the app shows."""
    config: VestaConfig = request.app["config"]
    state: State = request.app["state"]
    status = state.provider_status
    return web.json_response(
        {
            **config.model_dump(mode="json"),
            "authed": status is not None and status.state == ProviderAuthState.AUTHENTICATED,
            "kind": status.kind if status is not None else "none",
            # vestad gates "alive" on this: an authenticated agent that hasn't yet finished first-start
            # setup (or whose first model call failed) is not ready.
            "setup_complete": state.persisted.first_start_done,
        }
    )


async def _config_schema_handler(request: web.Request) -> web.Response:
    """The config's JSON schema, so the client renders/filters the settings UI off the one model."""
    return web.json_response(VestaConfig.model_json_schema())


async def _config_put_handler(request: web.Request) -> web.Response:
    """Update the agent's preferences (model, context, thinking, personality, timezone, seed_context).
    Writes the config store; the change is applied by the next restart (callers write, then restart
    once). Credentials are not set here — they go through PUT/DELETE /config/auth."""
    config: VestaConfig = request.app["config"]
    try:
        data = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    try:
        updates = validate_config_updates(config, data)
    except pyd.ValidationError as e:
        return web.json_response({"error": f"invalid config: {e.errors(include_url=False)}"}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if not updates:
        return web.json_response({"error": "no config provided"}, status=400)
    try:
        update_config_store(updates)
    except OSError as e:
        return web.json_response({"error": f"failed to write config: {e}"}, status=500)
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


_SHUTDOWN_TIMEOUT_S = 5.0  # bound the WS server drain on shutdown


async def start_ws_server(
    event_bus: EventBus,
    config: VestaConfig,
    state: State | None = None,
    *,
    # Loopback only: the container runs with host networking and vestad's proxy
    # reaches this server via localhost, so binding 127.0.0.1 keeps the agent API
    # off the LAN (and, behind the cloud firewall, off every external interface).
    host: str = "127.0.0.1",
) -> web.AppRunner:
    app = web.Application(middlewares=[_auth_middleware])
    app["event_bus"] = event_bus
    app["agent_token"] = config.agent_token.get_secret_value() if config.agent_token is not None else None
    app["config"] = config
    app["state"] = state
    app["websockets"] = weakref.WeakSet()
    app.on_shutdown.append(_close_all_websockets)
    app.router.add_get("/ws", _ws_handler)
    app.router.add_get("/history", _history_handler)
    app.router.add_get("/search", _search_handler)
    app.router.add_get("/provider/usage", _provider_usage_handler)
    app.router.add_get("/config", _config_get_handler)
    app.router.add_get("/config/schema", _config_schema_handler)
    app.router.add_put("/config", _config_put_handler)
    app.router.add_put("/config/auth", _config_auth_put_handler)
    app.router.add_delete("/config/auth", _config_auth_delete_handler)
    app.router.add_get("/memory", _memory_get_handler)
    app.router.add_put("/memory", _memory_put_handler)

    runner = web.AppRunner(app, shutdown_timeout=_SHUTDOWN_TIMEOUT_S)
    await runner.setup()
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
