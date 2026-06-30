"""Agent HTTP/WS server.

Routes:
  - WS   /ws                   bidirectional event bus
  - GET  /history              paginated event history (cursor optional), or full-text search with ?q=
  - GET  /usage                normalized, provider-agnostic plan usage
  - GET  /status               operational readiness: {authed, setup_complete} (vestad polls this)
  - GET  /config               prefs only (personality, timezone, seed_context, operational)
  - PUT  /config               update prefs (provider is set via /provider)
  - GET  /provider             active provider (configured fields) + derived {authed}
  - PUT  /provider             sign in / switch provider (claude credentials or openrouter key)
  - PATCH /provider            change model / context / thinking on the active provider
  - DELETE /provider           sign out: clear credentials, leaving not_authenticated
  - GET  /config/notification-policy   the policy: {rules, defaults} (ordered ruleset + per-(source, type) overrides)
  - PUT  /config/notification-policy   replace either/both sections; body {rules?, defaults?} (LIVE — applies next tick)
  Writes don't restart; the caller applies them with one restart afterwards. The
  notification endpoint is LIVE — applied on the next monitor tick, no restart.
  - GET  /memory               read MEMORY.md
  - PUT  /memory               overwrite MEMORY.md (applies on next restart)
"""

import asyncio
import dataclasses as dc
import json
import logging
import typing as tp
import sqlite3
import weakref
from collections.abc import Callable

import aiohttp as _aiohttp
import pydantic as pyd
from aiohttp import web

from .events import ChatEvent, EventBus, SnapshotChat, SnapshotEvent, UserEvent, VestaEvent
from .config import VestaConfig, stored_config, update_config_store, validate_config_updates
from .helpers import get_memory_path
from .models import State, TYPE_NOTIFICATION_POLICY_CHANGE
from .provider import ProviderAuthState, UsageError, clear_provider, get_usage, set_claude, set_openrouter
from . import notification_interrupt_policy


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
            events = event_bus.search(query, limit=limit if limit is not None else 20)
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
    """Prefs only (personality, timezone, seed_context, operational), secrets redacted. The provider
    is its own resource at GET /provider."""
    config: VestaConfig = request.app["config"]
    data = stored_config(config)
    data.pop("provider", None)
    return web.json_response(data)


async def _config_put_handler(request: web.Request) -> web.Response:
    """Update prefs (personality, timezone, seed_context). The provider is set via /provider, not here.
    Applied by the next restart (callers write, then restart once)."""
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
        update_config_store(updates)
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
            state.provider_status = set_claude(signin.credentials, signin.model, signin.max_context_tokens, config=config)
        else:
            state.provider_status = set_openrouter(signin.key, signin.model, signin.max_context_tokens, config=config)
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
        update_config_store(updates)
    except OSError as e:
        return web.json_response({"error": f"failed to write config: {e}"}, status=500)
    return web.json_response({"ok": True})


async def _provider_delete_handler(request: web.Request) -> web.Response:
    """Sign out: clear the provider credentials, resetting to a valid signed-out state. Idempotent.
    Applied by the next restart."""
    state: State = request.app["state"]
    config: VestaConfig = request.app["config"]
    try:
        state.provider_status = clear_provider(config=config)
    except OSError as e:
        return web.json_response({"error": f"sign out failed: {e}"}, status=500)
    return web.json_response({"ok": True})


# The notification policy is one file with two live-edited sections: an ordered interrupt `rules` list
# and per-(source, type) `defaults` overrides. One endpoint serves both. A PUT replaces only the
# sections present in the body, so the rules card and the defaults card each write independently
# without clobbering the other (save_* is a read-modify-write that preserves the untouched section).
# Unlike the other /config writes, this is LIVE — monitor_loop picks the change up on the next tick.
_POLICY_SECTIONS: dict[str, tuple[type[pyd.BaseModel], Callable[[list[tp.Any], VestaConfig], list[tp.Any]]]] = {
    "rules": (notification_interrupt_policy.NotificationInterruptRule, notification_interrupt_policy.save_rules),
    "defaults": (notification_interrupt_policy.NotificationDefault, notification_interrupt_policy.save_defaults),
}


def _policy_response(config: VestaConfig) -> web.Response:
    rules, defaults = notification_interrupt_policy.load_policy(config)
    return web.json_response({"rules": [rule.model_dump() for rule in rules], "defaults": [default.model_dump() for default in defaults]})


async def _config_notification_policy_get_handler(request: web.Request) -> web.Response:
    config: VestaConfig = request.app["config"]
    return await asyncio.to_thread(_policy_response, config)


def _policy_change_summary(validated: dict[str, list[pyd.BaseModel]]) -> str:
    """A plain-language recap of the sections the user just saved, for the core notification that tells
    the agent its policy was retuned. Renders each entry from its model_dump (no per-model coupling)."""

    def render(item: pyd.BaseModel) -> str:
        dumped = item.model_dump()
        conds = [f"{key}={dumped[key]}" for key in ("source", "type") if key in dumped and dumped[key] not in (None, "")]
        # Rules carry their remaining conditions as `match` predicates (sender/keyword were folded into
        # these); defaults have no match key, so this loop is skipped for them.
        for pred in dumped["match"] if "match" in dumped else []:
            rel = "matches" if pred["op"] == "regex" else "contains"
            negate = "not " if pred["negate"] else ""
            conds.append(f"{pred['field']} {negate}{rel} {pred['value']!r}")
        action = dumped["action"] if "action" in dumped else "?"
        return f"{', '.join(conds) or 'any'} -> {action}"

    parts: list[str] = []
    for key, label in (("rules", "interrupt rules"), ("defaults", "default overrides")):
        if key in validated:
            items = validated[key]
            parts.append(f"{label} ({len(items)}): " + ("; ".join(render(item) for item in items) if items else "none"))
    body = " and ".join(parts) if parts else "your notification policy"
    return (
        "[The user updated your notification interrupt policy from the app — you didn't make this change; "
        f"it's already live.] Now: {body}. If any of this is wrong for your focus, raise it with the user."
    )


async def _config_notification_policy_put_handler(request: web.Request) -> web.Response:
    config: VestaConfig = request.app["config"]
    try:
        data = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    if not isinstance(data, dict):
        return web.json_response({"error": "body must be an object with 'rules' and/or 'defaults' lists"}, status=400)
    present = {key: data[key] for key in _POLICY_SECTIONS if key in data}
    if not present or any(not isinstance(value, list) for value in present.values()):
        return web.json_response({"error": "body must contain at least one of 'rules'/'defaults' as a list"}, status=400)
    # Validate every present section before saving any, so a malformed 'defaults' can't land a partial
    # write that already persisted 'rules'.
    validated: dict[str, list[pyd.BaseModel]] = {}
    for key, value in present.items():
        model_cls, _save = _POLICY_SECTIONS[key]
        try:
            validated[key] = [model_cls.model_validate(item) for item in value]
        except pyd.ValidationError as e:
            return web.json_response({"error": f"invalid {key}: {e.errors(include_url=False)}"}, status=400)
    try:
        for key, items in validated.items():
            _model_cls, save = _POLICY_SECTIONS[key]
            await asyncio.to_thread(save, items, config)
    except OSError as e:
        return web.json_response({"error": f"failed to write notification policy: {e}"}, status=500)
    # Surface the change to the agent in-context (pooled core notification): the agent's own edits go
    # through the skill's direct file write, never this endpoint, so this fires only for user changes.
    # Deferred import: loops pulls heavy deps and would be a wide import at module load.
    from .loops import drop_core_notification

    await asyncio.to_thread(
        drop_core_notification,
        type_=TYPE_NOTIFICATION_POLICY_CHANGE,
        body=_policy_change_summary(validated),
        interrupt=False,
        config=config,
    )
    return await asyncio.to_thread(_policy_response, config)


async def _notifications_static_defaults_handler(request: web.Request) -> web.Response:
    """The static interrupt fallback per (source, type), aggregated in one query over the whole
    history. The defaults card uses this instead of paging every notification page client-side."""
    event_bus: EventBus = request.app["event_bus"]
    defaults = await asyncio.to_thread(event_bus.notification_static_defaults)
    return web.json_response({"defaults": defaults})


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
    app.router.add_get("/usage", _usage_handler)
    app.router.add_get("/status", _status_handler)
    app.router.add_get("/config", _config_get_handler)
    app.router.add_put("/config", _config_put_handler)
    app.router.add_get("/provider", _provider_get_handler)
    app.router.add_put("/provider", _provider_put_handler)
    app.router.add_patch("/provider", _provider_patch_handler)
    app.router.add_delete("/provider", _provider_delete_handler)
    app.router.add_get("/config/notification-policy", _config_notification_policy_get_handler)
    app.router.add_put("/config/notification-policy", _config_notification_policy_put_handler)
    app.router.add_get("/notifications/static-defaults", _notifications_static_defaults_handler)
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
