"""The app-chat service: POST /message (intake) and GET /history (paged conversation). Registered with
vestad as the `app-chat` service, reached by clients through the authenticated proxy. Intake here (not
a core sidecar) keeps the `user` echo an honest delivery receipt: persist + echo + notification happen
in the request coroutine, so a client that got a 200 knows its message is durable and delivered."""

import collections
import datetime as dt
import json
import logging
import pathlib as pl
import time
import typing as tp

from aiohttp import web

from .store import Store, StoredEvent

logger = logging.getLogger("app-chat.service")

# Bound on the recently-seen intent_id set: the newest N intents dedup a retried send-message; older
# ones age out (a retry that far behind is not a real double-send). Moved here from core State.
_SEEN_INTENT_IDS_CAP = 256

EmitFn = tp.Callable[[StoredEvent], None]


class ServiceState:
    def __init__(self, store: Store, notifications_dir: pl.Path, emit: EmitFn) -> None:
        self.store = store
        self.notifications_dir = notifications_dir
        self.emit = emit
        self.seen_intent_ids: collections.OrderedDict[str, None] = collections.OrderedDict()

    def remember(self, intent_id: str) -> None:
        self.seen_intent_ids[intent_id] = None
        while len(self.seen_intent_ids) > _SEEN_INTENT_IDS_CAP:
            self.seen_intent_ids.popitem(last=False)


_STATE_KEY: web.AppKey[ServiceState] = web.AppKey("state", ServiceState)


def _write_notification(state: ServiceState, text: str, intent_id: str | None) -> None:
    """Persist an inbound app message as the source=app-chat notification the monitor loop turns into a
    model turn. Byte-identical to core's former _write_app_chat_notification: the reply_hint and the
    intent_id extra ride along unchanged so the model side sees no difference."""
    directory = state.notifications_dir
    directory.mkdir(parents=True, exist_ok=True)
    fields: dict[str, object] = {
        "timestamp": dt.datetime.now().isoformat(),
        "source": "app-chat",
        "type": "message",
        "message": text,
        "interrupt": True,
        "reply_hint": "reply with `app-chat send`, and think about how you can best show your personality",
    }
    if intent_id is not None:
        fields["intent_id"] = intent_id
    path = directory / f"{time.time_ns()}-app-chat-message.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(fields))
    tmp.replace(path)


async def message_handler(request: web.Request) -> web.Response:
    """Intake one app message: dedup by intent_id, write the notification (the fallible step), then
    persist the user event (skill-assigned id) and emit the live echo, recording the intent last. A
    repeat intent_id is a retry (client resends on 5xx/timeout): a deduped repeat is dropped whole (no
    second echo, no second intake), and a repeat after a failed write re-runs the intake exactly once."""
    state = request.app[_STATE_KEY]
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    if not isinstance(body, dict) or "text" not in body or not isinstance(body["text"], str):
        return web.json_response({"error": "body must be {text: string}"}, status=400)
    text = body["text"].strip()
    if not text:
        return web.json_response({"error": "empty message"}, status=400)

    intent_id = body["intent_id"] if "intent_id" in body and isinstance(body["intent_id"], str) else None
    if intent_id is not None and intent_id in state.seen_intent_ids:
        logger.debug("dropping duplicate app-chat message intent_id=%s", intent_id)
        return web.json_response({"ok": True, "deduped": True})

    event: StoredEvent = {"type": "user", "ts": dt.datetime.now(dt.UTC).isoformat(), "text": text}
    method = body["input_method"] if "input_method" in body else None
    if isinstance(method, str) and method in ("voice", "typed"):
        event["input_method"] = method
    if intent_id is not None:
        event["intent_id"] = intent_id

    # The notification file is the only fallible side effect (file IO), so write it first: on failure
    # nothing is persisted, echoed, or remembered, and with no await between here and the return the
    # client's retry (same intent_id) re-runs the whole intake exactly once. Only a successful write
    # persists + echoes + records the intent, keeping intake at-most-once.
    try:
        _write_notification(state, text, intent_id)
    except OSError as exc:
        logger.error("failed to write app-chat notification: %s", exc)
        return web.json_response({"error": "intake write failed"}, status=500)
    state.store.append(event)
    state.emit(event)
    if intent_id is not None:
        state.remember(intent_id)
    return web.json_response({"ok": True, "id": event["id"]})


async def history_handler(request: web.Request) -> web.Response:
    """Paged conversation, oldest-to-newest, {events, cursor}. Matches what clients consumed from core
    /history channel=app-chat: pass the returned cursor to fetch the next older page; null means none."""
    state = request.app[_STATE_KEY]
    limit_raw = request.query.get("limit", "")
    try:
        limit = int(limit_raw) if limit_raw else None
    except ValueError:
        return web.json_response({"error": "invalid limit"}, status=400)
    cursor_raw = request.query.get("cursor", "")
    try:
        cursor = int(cursor_raw) if cursor_raw else None
    except ValueError:
        return web.json_response({"error": "invalid cursor"}, status=400)
    kwargs = {"limit": limit} if limit is not None else {}
    events, next_cursor = state.store.page(before_cursor=cursor, **kwargs)
    return web.json_response({"events": events, "cursor": next_cursor})


def create_app(state: ServiceState) -> web.Application:
    app = web.Application()
    app[_STATE_KEY] = state
    app.router.add_post("/message", message_handler)
    app.router.add_get("/history", history_handler)
    app.router.add_get("/health", lambda _: web.Response(text="ok"))
    return app
