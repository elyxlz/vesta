"""Agent HTTP/WS server.

Routes:
  - WS   /ws                   bidirectional event bus
  - GET  /history              paginated event history (cursor optional), or full-text search with ?q=
  - GET  /usage                normalized, provider-agnostic plan usage
  - GET  /status               operational readiness: {authed, setup_complete} (vestad polls this)
  - GET  /config               prefs + notification_rules (personality, timezone, seed_context, operational)
  - PUT  /config               update prefs and/or notification_rules (provider is set via /provider)
  - GET  /provider             active provider (configured fields) + derived {authed}
  - PUT  /provider             sign in / switch provider (claude credentials or openrouter key)
  - PATCH /provider            change model / context / thinking on the active provider
  - DELETE /provider           sign out: clear credentials, leaving not_authenticated
  - GET  /memory               read MEMORY.md
  - PUT  /memory               overwrite MEMORY.md (applies on next restart)

  Prefs writes apply on the caller's next restart; notification_rules apply live (monitor_loop
  re-reads them from the store each tick), so the rules editor and the skill need no restart.
"""

import asyncio
import dataclasses as dc
import datetime as dt
import json
import logging
import typing as tp
import sqlite3
import time
import weakref

import aiohttp as _aiohttp
import pydantic as pyd
from aiohttp import web

from .events import ChatEvent, EventBus, SnapshotChat, SnapshotEvent, UserEvent, VestaEvent
from .config import (
    ClaudeConfig,
    VestaConfig,
    atomic_write_text,
    load_notification_rules,
    stored_config,
    update_config_store,
    validate_config_updates,
)
from .helpers import get_memory_path
from .models import State
from .notification import Notification
from .provider import ProviderAuthState, UsageError, clear_provider, get_usage, set_claude, set_openrouter


logger = logging.getLogger("vesta.api")


def _pending_notification_ids(config: VestaConfig) -> list[str]:
    """Notification file stems still on disk — received but not yet processed. Seeds the connect
    snapshot's `notifications.pending`; run off the loop by the caller (globs the dir)."""
    directory = config.notifications_dir
    if not directory.exists():
        return []
    return [p.stem for p in directory.glob("*.json") if p.is_file()]


async def _ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Bidirectional event bus WebSocket.

    Send: all events from the event bus are pushed to connected clients.
    Recv: clients can emit events (e.g. user messages, chat replies).
    On connect: sends a `snapshot` seed (state + chat + pending notifications); ?skip_history=1
    omits the chat backlog for lightweight taps."""
    event_bus: EventBus = request.app["event_bus"]
    config: VestaConfig = request.app["config"]
    skip_history = request.query.get("skip_history", "") in ("1", "true")

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app["websockets"].add(ws)

    sub = event_bus.subscribe()
    recv_task: asyncio.Task[None] | None = None
    send_task: asyncio.Task[None] | None = None
    try:
        # The connect snapshot: one event seeding the client with current agent state. `chat` is the
        # app-chat conversation (notifications/internal events still arrive live but never bury the
        # capped recent window) — skipped with ?skip_history=1 for lightweight taps. `notifications`
        # carries the ids still on disk so the view can mark pending without polling. Always sent, even
        # empty, so the client can tell "still loading" from "no messages". Reads run off the loop: a
        # slow scan must not freeze the agent (it would starve vestad's status poll and flap "starting").
        if skip_history:
            chat = SnapshotChat(events=[], cursor=None)
        else:
            events, cursor = await asyncio.to_thread(event_bus.recent, channel="app-chat")
            chat = SnapshotChat(events=events, cursor=cursor)
        pending = await asyncio.to_thread(_pending_notification_ids, config)
        await ws.send_json(SnapshotEvent(type="snapshot", state=event_bus.state, chat=chat, notifications={"pending": pending}))
        recv_task = asyncio.create_task(_recv_loop(ws, event_bus, config))
        send_task = asyncio.create_task(_send_loop(ws, sub))
        await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)
    finally:
        tasks = [task for task in (recv_task, send_task) if task]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        event_bus.unsubscribe(sub)
        request.app["websockets"].discard(ws)

    return ws


def _write_app_chat_notification(config: VestaConfig, text: str) -> None:
    """Persist an inbound app message as a `source=app-chat` notification file — the in-process
    intake the monitor loop picks up. This is what actually delivers app chat to the model.

    Written here, in the same coroutine that receives the message, so intake no longer rides the
    broadcast bus through the app-chat sidecar daemon: that subscriber could die (OOM, never
    respawned after a restore) and silently drop messages the UI had already echoed as delivered,
    and the bus drops the oldest event under load — both wrong for delivery-critical intake."""
    directory = config.notifications_dir
    directory.mkdir(parents=True, exist_ok=True)
    # `message` is an extra field (Notification allows extras); it renders as the notification's
    # text, matching what the app-chat sidecar used to write. model_validate takes the dict so the
    # extra passes the type checker.
    notif = Notification.model_validate(
        {"timestamp": dt.datetime.now(), "source": "app-chat", "type": "message", "message": text, "interrupt": True}
    )
    path = directory / f"{time.time_ns()}-app-chat-message.json"
    atomic_write_text(path, notif.model_dump_json())


async def _recv_loop(ws: web.WebSocketResponse, event_bus: EventBus, config: VestaConfig) -> None:
    """Receive events from clients and emit to event bus."""
    async for msg in ws:
        if msg.type == web.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict) or "type" not in data:
                continue
            msg_type = data["type"]
            if msg_type in ("message", "chat"):
                if "text" not in data or not isinstance(data["text"], str):
                    continue
                text = data["text"].strip()
                if text:
                    if msg_type == "message":
                        # The `user` event is history + broadcast (the chat's own echo of the
                        # message). Intake — turning the message into the notification the model
                        # processes — is the file write below, done in-process off the loop.
                        event: UserEvent = {"type": "user", "text": text}
                        if "input_method" in data and data["input_method"] in ("voice", "typed"):
                            event["input_method"] = data["input_method"]
                        event_bus.emit(event)
                        try:
                            await asyncio.to_thread(_write_app_chat_notification, config, text)
                        except OSError as e:
                            # A lost intake write must surface loudly, never masquerade as delivered.
                            logger.error("failed to write app-chat notification: %s", e)
                    else:
                        event_bus.emit(ChatEvent(type="chat", text=text))
        elif msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
            break


# Bound on a single WS send. A half-open socket (peer gone, TCP not yet timed out) blocks
# send_json indefinitely while the subscriber queue overflows behind it; timing out closes
# the socket promptly so the client reconnects instead of lingering wedged for minutes.
_SEND_TIMEOUT_S = 30.0


async def _send_loop(ws: web.WebSocketResponse, sub: asyncio.Queue[VestaEvent]) -> None:
    """Forward all event-bus events to the WS client. Exits on the bus's eviction sentinel or a
    stalled send; the handler then closes the WS so the client reconnects and resyncs."""
    try:
        while True:
            event = await sub.get()
            if event["type"] == "evicted":
                logger.info("subscriber evicted by event bus, closing ws")
                break
            await asyncio.wait_for(ws.send_json(event), timeout=_SEND_TIMEOUT_S)
    except asyncio.CancelledError:
        pass
    except TimeoutError:
        logger.info("ws send stalled for %.0fs, closing", _SEND_TIMEOUT_S)
    except (ConnectionError, RuntimeError, TypeError) as e:
        logger.info(f"ws send_loop exited: {type(e).__name__}: {e}")


async def _history_handler(request: web.Request) -> web.Response:
    """Paginated event history, or full-text search when `q` is given (both return matching events in
    the same shape; search has no cursor).

    Query params:
      q       (str, optional): FTS5 search; returns events ranked by relevance (cursor is null).
      cursor  (int, optional): fetch events before this id. Omit for most recent. Ignored with `q`.
      limit   (int, optional): max events to return (default: EventBus.PAGE_SIZE; 20 for search).
      channel (str, optional): "app-chat" filters to the conversation event types. Ignored with `q`.
    """
    event_bus: EventBus = request.app["event_bus"]

    limit_raw = request.query.get("limit", "")
    try:
        limit = int(limit_raw) if limit_raw else None
    except ValueError:
        return web.json_response({"error": "invalid limit"}, status=400)

    query = request.query.get("q", "").strip()
    if query:
        try:
            events = await asyncio.to_thread(event_bus.search, query, limit=limit if limit is not None else 20)
        except sqlite3.OperationalError as e:
            # FTS5 raises OperationalError for a malformed MATCH expression: that's a client error.
            logger.warning(f"search query rejected: {e}")
            return web.json_response({"error": "invalid search query"}, status=400)
        except sqlite3.Error as e:
            # A genuine SQLite fault (locked db, disk full, corrupted FTS) must surface, not masquerade as a bad query.
            logger.error(f"search failed for query={query!r}: {e}")
            return web.json_response({"error": "search failed"}, status=500)
        return web.json_response({"events": events, "cursor": None})

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


async def _usage_handler(request: web.Request) -> web.Response:
    """Report normalized, provider-agnostic plan usage for the agent's active provider."""
    config = request.app["config"]
    try:
        usage = await get_usage(config)
    except UsageError as e:
        logger.error(f"usage fetch failed: {e}")
        return web.json_response({"error": str(e)}, status=502)
    return web.json_response(dc.asdict(usage))


async def _config_get_handler(request: web.Request) -> web.Response:
    """Prefs + notification_rules (secrets redacted). The provider is its own resource at GET /provider.
    notification_rules is overlaid from the store, not the boot-time config, so it reflects live edits
    (the skill relies on this read-modify-write to append/remove rules without a restart)."""
    config: VestaConfig = request.app["config"]
    data = stored_config(config)
    data.pop("provider", None)
    data["notification_rules"] = [rule.model_dump() for rule in load_notification_rules()]
    return web.json_response(data)


async def _config_put_handler(request: web.Request) -> web.Response:
    """Update prefs (personality, timezone, seed_context) and/or notification_rules. The provider is set
    via /provider, not here. Prefs apply on the caller's next restart; notification_rules apply live
    (monitor_loop re-reads them from the store each tick), so a rules-only write needs no restart."""
    config: VestaConfig = request.app["config"]
    try:
        data = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    if isinstance(data, dict) and "provider" in data:
        return web.json_response({"error": "provider is set via PUT/PATCH /provider"}, status=400)
    try:
        updates = validate_config_updates(config, data)
    except pyd.ValidationError as e:
        return web.json_response({"error": f"invalid config: {e.errors(include_url=False)}"}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if not updates:
        return web.json_response({"error": "no config provided"}, status=400)
    try:
        await asyncio.to_thread(update_config_store, updates)
    except OSError as e:
        return web.json_response({"error": f"failed to write config: {e}"}, status=500)
    return web.json_response({"ok": True})


class _ClaudeSignIn(pyd.BaseModel):
    kind: tp.Literal["claude"]
    # None on re-auth: preserve the agent's existing model rather than reset it.
    model: tp.Literal["opus", "sonnet", "haiku"] | None = None
    max_context_tokens: int | None = None
    credentials: str


class _OpenRouterSignIn(pyd.BaseModel):
    kind: tp.Literal["openrouter"]
    model: str
    max_context_tokens: int | None = None
    key: str


_ProviderSignIn = tp.Annotated[_ClaudeSignIn | _OpenRouterSignIn, pyd.Field(discriminator="kind")]
_SIGN_IN_ADAPTER: pyd.TypeAdapter[_ClaudeSignIn | _OpenRouterSignIn] = pyd.TypeAdapter(_ProviderSignIn)


class _ProviderPrefs(pyd.BaseModel):
    """The PATCH /provider body: change the active provider's settable knobs (no credential change)."""

    model_config = pyd.ConfigDict(extra="forbid")

    model: str | None = None
    max_context_tokens: int | None = None
    thinking: str | None = None


async def _provider_get_handler(request: web.Request) -> web.Response:
    """The active provider: its configured fields (key redacted, oauth excluded) plus the derived
    `authed` flag (whether its credentials are currently valid). Readiness lives at GET /status."""
    config: VestaConfig = request.app["config"]
    state: State = request.app["state"]
    status = state.provider_status
    provider = stored_config(config)["provider"]
    body = dict(provider) if isinstance(provider, dict) else {}
    body["authed"] = status is not None and status.state == ProviderAuthState.AUTHENTICATED
    # The Claude plan tier (from the on-disk OAuth blob, excluded from stored_config) so the context
    # picker can restrict >200K windows to Max, the only plan entitled to the 1M-context beta.
    if isinstance(config.provider, ClaudeConfig) and config.provider.oauth is not None:
        body["plan"] = config.provider.oauth.subscriptionType
    return web.json_response(body)


async def _status_handler(request: web.Request) -> web.Response:
    """The agent's operational readiness: whether the active provider is authenticated, whether one is
    configured at all (so vestad can tell unprovisioned from unauthenticated), and whether first-start
    has finished. vestad polls this to gate Alive / SettingUp / NotAuthenticated / Unprovisioned (an
    authenticated agent that hasn't finished first-start is not yet ready)."""
    state: State = request.app["state"]
    status = state.provider_status
    return web.json_response(
        {
            "authed": status is not None and status.state == ProviderAuthState.AUTHENTICATED,
            "provider_configured": status is not None and status.kind != "none",
            "setup_complete": state.persisted.first_start_done,
        }
    )


async def _provider_put_handler(request: web.Request) -> web.Response:
    """Sign in / switch provider: `{kind:"claude", model, credentials}` (OAuth blob written to the SDK
    file, never stored) or `{kind:"openrouter", model, key}`. Applied by the next restart."""
    state: State = request.app["state"]
    config: VestaConfig = request.app["config"]
    try:
        raw = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    try:
        signin = _SIGN_IN_ADAPTER.validate_python(raw)
    except pyd.ValidationError as e:
        return web.json_response({"error": f"invalid provider: {e.errors(include_url=False)}"}, status=400)
    try:
        if isinstance(signin, _ClaudeSignIn):
            state.provider_status = await asyncio.to_thread(
                set_claude, signin.credentials, signin.model, signin.max_context_tokens, config=config
            )
        else:
            state.provider_status = await asyncio.to_thread(set_openrouter, signin.key, signin.model, signin.max_context_tokens, config=config)
    except (json.JSONDecodeError, TypeError) as e:
        return web.json_response({"error": f"invalid credentials: {e}"}, status=400)
    except OSError as e:
        return web.json_response({"error": f"auth write failed: {e}"}, status=500)
    return web.json_response({"ok": True})


async def _provider_patch_handler(request: web.Request) -> web.Response:
    """Change the active provider's settable knobs (model / context / thinking), deep-merged onto the
    current provider and re-validated. No credential change. Applied by the next restart."""
    config: VestaConfig = request.app["config"]
    try:
        raw = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    try:
        prefs = _ProviderPrefs.model_validate(raw)
    except pyd.ValidationError as e:
        return web.json_response({"error": f"invalid provider prefs: {e.errors(include_url=False)}"}, status=400)
    patch = prefs.model_dump(exclude_unset=True)
    if not patch:
        return web.json_response({"error": "no provider fields provided"}, status=400)
    try:
        updates = validate_config_updates(config, {"provider": patch})
    except pyd.ValidationError as e:
        return web.json_response({"error": f"invalid provider: {e.errors(include_url=False)}"}, status=400)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    try:
        await asyncio.to_thread(update_config_store, updates)
    except OSError as e:
        return web.json_response({"error": f"failed to write config: {e}"}, status=500)
    return web.json_response({"ok": True})


async def _provider_delete_handler(request: web.Request) -> web.Response:
    """Sign out: clear the provider credentials, resetting to a valid signed-out state. Idempotent.
    Applied by the next restart."""
    state: State = request.app["state"]
    config: VestaConfig = request.app["config"]
    try:
        state.provider_status = await asyncio.to_thread(clear_provider, config=config)
    except OSError as e:
        return web.json_response({"error": f"sign out failed: {e}"}, status=500)
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
    if not isinstance(data, dict) or "content" not in data or not isinstance(data["content"], str):
        return web.json_response({"error": "body must be {content: string}"}, status=400)
    path = get_memory_path(config)
    await asyncio.to_thread(atomic_write_text, path, data["content"])
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
    app.router.add_get("/usage", _usage_handler)
    app.router.add_get("/status", _status_handler)
    app.router.add_get("/config", _config_get_handler)
    app.router.add_put("/config", _config_put_handler)
    app.router.add_get("/provider", _provider_get_handler)
    app.router.add_put("/provider", _provider_put_handler)
    app.router.add_patch("/provider", _provider_patch_handler)
    app.router.add_delete("/provider", _provider_delete_handler)
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
