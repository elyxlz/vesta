"""The app-chat service: POST /message (intake), GET /history (paged conversation), and GET /ws (the
replay-free live chat stream). Registered with vestad as the `app-chat` service, reached by clients
through the authenticated proxy. Intake here (not a core sidecar) keeps the `user` echo an honest
delivery receipt: persist + echo + notification happen in the request coroutine, so a client that got
a 200 knows its message is durable and delivered. The echo fans out to /ws subscribers in-process, so
the skill owns the chat plane end to end with no dependency on core's bus."""

import asyncio
import collections
import datetime as dt
import json
import logging
import pathlib as pl
import time
import typing as tp
import urllib.parse

from aiohttp import web

from . import attachments
from .store import Store, StoredEvent

logger = logging.getLogger("app-chat.service")

# The intake body cap: one upload chunk plus headroom. Uploads are chunked client-side precisely so no
# single request ever needs more than this (vestad's proxy buffers request bodies at 10 MiB above us).
_CLIENT_MAX_SIZE = attachments.MAX_CHUNK_BYTES + 1024 * 1024

# The body cap above is sized for upload chunks and applies app-wide, so message text carries its own
# ceiling: a message this large would otherwise land verbatim in the model's notification turn.
_MAX_TEXT_CHARS = 64 * 1024

# Mimes a browser may render inline. Everything else serves as a plain download under
# application/octet-stream: the declared mime is client input, and text/html rendered inline on the
# gateway origin would execute script beside the app's own tokens.
_INLINE_MIME_PREFIXES = ("image/", "video/", "audio/")
_INLINE_MIMES = ("application/pdf",)

_MIME_MAX_CHARS = 200


def _valid_mime(mime: str) -> bool:
    return 0 < len(mime) <= _MIME_MAX_CHARS and "/" in mime and all(" " <= char <= "~" for char in mime)


# Bound on the recently-seen intent_id set: the newest N intents dedup a retried send-message; older
# ones age out (a retry that far behind is not a real double-send). Moved here from core State.
_SEEN_INTENT_IDS_CAP = 256

# Per-connection outbound buffer for a chat-socket client. Bounded because the store holds the durable
# copy: a stalled client's oldest queued event is dropped rather than grow without limit; the client
# refetches the tail by id on its next reconnect (the socket is replay-free by design).
_WS_QUEUE_MAX = 256


class ServiceState:
    def __init__(self, store: Store, notifications_dir: pl.Path, attachments_root: pl.Path) -> None:
        self.store = store
        self.notifications_dir = notifications_dir
        self.attachments_root = attachments_root
        self.seen_intent_ids: collections.OrderedDict[str, None] = collections.OrderedDict()
        self.subscribers: set[asyncio.Queue[StoredEvent]] = set()

    def remember(self, intent_id: str) -> None:
        self.seen_intent_ids[intent_id] = None
        while len(self.seen_intent_ids) > _SEEN_INTENT_IDS_CAP:
            self.seen_intent_ids.popitem(last=False)

    def emit(self, event: StoredEvent) -> None:
        """Fan a freshly persisted event (user echo or chat reply) to every connected chat socket. A
        full queue drops its oldest so a wedged client never blocks intake; that client re-syncs by
        refetching history on reconnect."""
        for queue in list(self.subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)


_STATE_KEY: web.AppKey[ServiceState] = web.AppKey("state", ServiceState)


def _attachment_line(state: ServiceState, metas: list[attachments.AttachmentMeta]) -> str:
    """One scalar the notification renderer shows as an attribute: name, type, human size, and the
    absolute path the agent opens directly. Paths derive from the metas in hand: no disk reads here,
    the intake sequence stays synchronous."""
    parts = []
    for meta in metas:
        blob = state.attachments_root / meta["id"] / meta["name"]
        parts.append(f"{meta['name']} ({meta['mime']}, {attachments.human_size(meta['size'])}) at {blob}")
    return "; ".join(parts)


def _write_notification(state: ServiceState, text: str, metas: list[attachments.AttachmentMeta]) -> None:
    """Persist an inbound app message as the source=app-chat notification the monitor loop turns into a
    model turn. The structured reply command and behavioral hint ride along so the model receives the
    producer-owned response guidance. The client-only intent ID stays on the chat event."""
    directory = state.notifications_dir
    directory.mkdir(parents=True, exist_ok=True)
    fields: dict[str, object] = {
        "timestamp": dt.datetime.now().isoformat(),
        "source": "app-chat",
        "type": "message",
        "message": text,
        "interrupt": True,
        "reply_command": "app-chat send --message -",
        "reply_hint": "think about how you can best show your personality",
    }
    if metas:
        fields["attachments"] = _attachment_line(state, metas)
    path = directory / f"{time.time_ns()}-app-chat-message.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(fields))
    tmp.replace(path)


def _build_message_event(body: dict[str, object]) -> tuple[StoredEvent, list[str]] | str:
    """Validate an intake body into (the user event to persist, the attachment ids to resolve), or the
    client error to answer. Pure shape work: the event carries no attachments until the handler swaps
    the resolved metadata in, and no side effect happens here."""
    if "text" in body and not isinstance(body["text"], str):
        return "body must be {text?: string, attachments?: [id]}"
    text = body["text"].strip() if "text" in body and isinstance(body["text"], str) else ""
    if len(text) > _MAX_TEXT_CHARS:
        return f"message text is capped at {_MAX_TEXT_CHARS} characters"
    ids = body["attachments"] if "attachments" in body else []
    if not isinstance(ids, list) or not all(isinstance(one, str) for one in ids):
        return "attachments must be a list of ids"
    if len(ids) > attachments.MAX_ATTACHMENTS_PER_MESSAGE:
        return f"at most {attachments.MAX_ATTACHMENTS_PER_MESSAGE} attachments per message"
    if not text and not ids:
        return "empty message"
    event: StoredEvent = {"type": "user", "ts": dt.datetime.now(dt.UTC).isoformat(), "text": text}
    method = body["input_method"] if "input_method" in body else None
    if isinstance(method, str) and method in ("voice", "typed"):
        event["input_method"] = method
    intent_id = body["intent_id"] if "intent_id" in body else None
    if isinstance(intent_id, str):
        event["intent_id"] = intent_id
    return event, tp.cast(list[str], ids)


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
    built = _build_message_event(body) if isinstance(body, dict) else "invalid json body"
    if isinstance(built, str):
        return web.json_response({"error": built}, status=400)
    event, ids = built

    intent_id = event["intent_id"] if "intent_id" in event else None
    if intent_id is not None and intent_id in state.seen_intent_ids:
        logger.debug("dropping duplicate app-chat message intent_id=%s", intent_id)
        return web.json_response({"ok": True, "deduped": True})

    # Resolve ids to finalized metadata before any side effect: a miss is a 400 that persists nothing.
    # The reads are tiny metadata files, kept synchronous so no await enters the intake sequence.
    metas: list[attachments.AttachmentMeta] = []
    for attachment_id in ids:
        meta = attachments.read_meta(state.attachments_root, attachment_id)
        if meta is None:
            return web.json_response({"error": f"unknown attachment: {attachment_id}"}, status=400)
        metas.append(meta)
    if metas:
        event["attachments"] = metas
    text = event["text"]

    # The notification file is the only fallible side effect (file IO), so write it first: on failure
    # nothing is persisted, echoed, or remembered, and with no await between here and the return the
    # client's retry (same intent_id) re-runs the whole intake exactly once. Only a successful write
    # persists + echoes + records the intent, keeping intake at-most-once.
    try:
        _write_notification(state, text, metas)
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
    # The sqlite read runs off the event loop, so a large page never stalls the live WS fan-out.
    events, next_cursor = await asyncio.to_thread(state.store.page, before_cursor=cursor, **kwargs)
    return web.json_response({"events": events, "cursor": next_cursor})


async def health_handler(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    """Per-connection live chat stream: every event appended after connect (user echo, agent reply),
    no replay. Clients seed history over GET /history and reconcile this live edge by id. The inbound
    half is drained only to notice a client close."""
    state = request.app[_STATE_KEY]
    ws = web.WebSocketResponse(heartbeat=30.0)
    await ws.prepare(request)
    queue: asyncio.Queue[StoredEvent] = asyncio.Queue(maxsize=_WS_QUEUE_MAX)
    state.subscribers.add(queue)

    async def pump() -> None:
        while True:
            event = await queue.get()
            await ws.send_json(event)

    sender = asyncio.create_task(pump())
    try:
        async for msg in ws:
            if msg.type in (web.WSMsgType.ERROR, web.WSMsgType.CLOSE):
                break
    finally:
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
        except (ConnectionResetError, RuntimeError) as exc:
            logger.debug("chat-socket pump ended on a dead client: %s", exc)
        state.subscribers.discard(queue)
    return ws


async def attachment_create_handler(request: web.Request) -> web.Response:
    """Open an upload session for one declared file; the client then PUTs offset-addressed chunks."""
    state = request.app[_STATE_KEY]
    try:
        body = await request.json()
    except (json.JSONDecodeError, TypeError):
        return web.json_response({"error": "invalid json body"}, status=400)
    valid = (
        isinstance(body, dict)
        and "name" in body
        and isinstance(body["name"], str)
        and "mime" in body
        and isinstance(body["mime"], str)
        and "size" in body
        and isinstance(body["size"], int)
    )
    if not valid:
        return web.json_response({"error": "body must be {name, mime, size}"}, status=400)
    # The declared mime later becomes a response header; a control character there would make the
    # blob permanently unservable (header serialization refuses it), so reject it at the door.
    if not _valid_mime(body["mime"]):
        return web.json_response({"error": "invalid mime type"}, status=400)
    extra: attachments.AttachmentMeta = {}
    if "width" in body and isinstance(body["width"], int):
        extra["width"] = body["width"]
    if "height" in body and isinstance(body["height"], int):
        extra["height"] = body["height"]
    if "duration_secs" in body and isinstance(body["duration_secs"], (int, float)):
        extra["duration_secs"] = float(body["duration_secs"])
    try:
        attachment_id = await asyncio.to_thread(
            attachments.create_session, state.attachments_root, body["name"], body["mime"], body["size"], extra
        )
    except attachments.SizeError as exc:
        return web.json_response({"error": str(exc)}, status=413)
    return web.json_response({"id": attachment_id})


async def attachment_data_handler(request: web.Request) -> web.Response:
    """Append one chunk at an explicit offset. A 409 carries the staged size so the client resyncs; a
    replayed chunk whose bytes already landed reads received == offset + len as delivered."""
    state = request.app[_STATE_KEY]
    try:
        offset = int(request.query.get("offset", ""))
    except ValueError:
        return web.json_response({"error": "invalid offset"}, status=400)
    data = await request.read()
    try:
        received = await asyncio.to_thread(attachments.append_at, state.attachments_root, request.match_info["id"], offset, data)
    except attachments.UnknownAttachmentError:
        return web.json_response({"error": "unknown attachment"}, status=404)
    except attachments.OffsetMismatchError as exc:
        return web.json_response({"error": "offset mismatch", "received": exc.received}, status=409)
    except attachments.SizeError as exc:
        return web.json_response({"error": str(exc)}, status=413)
    return web.json_response({"ok": True, "received": received})


async def attachment_status_handler(request: web.Request) -> web.Response:
    """The resume probe: where to continue after a connection gap."""
    state = request.app[_STATE_KEY]
    try:
        received, size, finalized = await asyncio.to_thread(attachments.upload_status, state.attachments_root, request.match_info["id"])
    except attachments.UnknownAttachmentError:
        return web.json_response({"error": "unknown attachment"}, status=404)
    return web.json_response({"received": received, "size": size, "finalized": finalized})


async def attachment_complete_handler(request: web.Request) -> web.Response:
    """Finalize a fully staged upload. Idempotent, so a lost response is retried safely."""
    state = request.app[_STATE_KEY]
    try:
        meta = await asyncio.to_thread(attachments.finalize, state.attachments_root, request.match_info["id"])
    except attachments.UnknownAttachmentError:
        return web.json_response({"error": "unknown attachment"}, status=404)
    except attachments.SizeMismatchError as exc:
        return web.json_response({"error": str(exc)}, status=409)
    return web.json_response({"attachment": meta})


def _content_disposition(kind: str, name: str) -> str:
    """RFC 6266/5987: an ascii fallback plus the percent-encoded real name, so a unicode filename
    survives every browser instead of being mangled or truncated at a semicolon."""
    fallback = name.encode("ascii", "ignore").decode().replace('"', "").replace(";", "").replace("\\", "")
    if not fallback:
        fallback = "file"
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{urllib.parse.quote(name)}"


async def attachment_serve_handler(request: web.Request) -> web.StreamResponse:
    """Stream a finalized blob (FileResponse: Range works natively, so video seeking is free). A blob
    cleaned up by `app-chat attachments rm` keeps its meta and answers 410, which clients render as a
    terminal "no longer available" tile. Only media mimes serve inline: the declared mime is client
    input, so anything else downloads as an opaque octet-stream, and CSP sandbox covers what inline
    rendering remains (an SVG can script)."""
    state = request.app[_STATE_KEY]
    attachment_id = request.match_info["id"]
    meta = await asyncio.to_thread(attachments.read_meta, state.attachments_root, attachment_id)
    if meta is None:
        return web.json_response({"error": "unknown attachment"}, status=404)
    blob = state.attachments_root / attachment_id / meta["name"]
    if not await asyncio.to_thread(blob.exists):
        return web.json_response({"error": "attachment removed"}, status=410)
    inline_safe = meta["mime"].startswith(_INLINE_MIME_PREFIXES) or meta["mime"] in _INLINE_MIMES
    inline = inline_safe and request.query.get("download", "") != "1"
    return web.FileResponse(
        blob,
        headers={
            "Content-Type": meta["mime"] if inline_safe else "application/octet-stream",
            "Content-Disposition": _content_disposition("inline" if inline else "attachment", meta["name"]),
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
            # An hour of caching, not immutable forever: a blob freed by `attachments rm` must be able
            # to surface its 410 on clients that already viewed it.
            "Cache-Control": "private, max-age=3600",
        },
    )


def create_app(state: ServiceState) -> web.Application:
    app = web.Application(client_max_size=_CLIENT_MAX_SIZE)
    app[_STATE_KEY] = state
    app.router.add_post("/message", message_handler)
    app.router.add_get("/history", history_handler)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_post("/attachments", attachment_create_handler)
    app.router.add_put("/attachments/{id}/data", attachment_data_handler)
    app.router.add_get("/attachments/{id}/status", attachment_status_handler)
    app.router.add_post("/attachments/{id}/complete", attachment_complete_handler)
    app.router.add_get("/attachments/{id}", attachment_serve_handler)
    return app
