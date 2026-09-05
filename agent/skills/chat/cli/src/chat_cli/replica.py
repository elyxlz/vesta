"""The replica: every room this agent is in, mirrored from the node into the skill's own store. One
socket carries the live edge and one pull per room carries everything the store missed, both keyed by
the node's message id, so a message replicates exactly once however it arrives. Each message that is
not this agent's own echo becomes the notification the monitor loop turns into a turn, and each
attachment it carries lands in the local blob store first, so the notification names a path the agent
opens. Every sqlite and file operation runs off the event loop."""

import asyncio
import contextlib
import json
import logging
import pathlib as pl
import sqlite3
from dataclasses import dataclass

import aiohttp

from . import attachments, notifications
from .attachments import AttachmentMeta
from .node_client import JsonValue, NodeClient, NodeError, NodeMessage, parse_message, parse_room
from .store import Store, StoredEvent, direct_room_id

logger = logging.getLogger("chat.replica")

# One pull page. Large, because a catch-up after a long outage is one round trip per page.
REPLICA_PAGE_SIZE = 500
REPLICA_RECONNECT_BASE_SECS = 1.0
REPLICA_RECONNECT_MAX_SECS = 30.0

# The live frames that are not messages. A message frame carries its own `type` (`user` or `chat`).
_ROOM_CREATED = "room_created"
_ROOM_DELETED = "room_deleted"
_USER_FINISHED_TALKING = "user_finished_talking"
_ROOM_EVENTS = (_ROOM_CREATED, _ROOM_DELETED, _USER_FINISHED_TALKING)

_MESSAGE_NOTIFICATION = "message"


@dataclass
class ReplicaState:
    store: Store
    client: NodeClient
    attachments_root: pl.Path
    notifications_dir: pl.Path
    agent: str
    connected: bool = False


async def catch_up(state: ReplicaState) -> int:
    """Every room the node has this agent in, and everything each room holds past the newest node id
    the store carries for it. Answers how many messages this pull persisted."""
    ingested = 0
    for room in await state.client.rooms():
        await asyncio.to_thread(state.store.upsert_room, room)
        after = await asyncio.to_thread(state.store.max_node_id, room["id"])
        while True:
            page, cursor = await state.client.history_after(room["id"], after, REPLICA_PAGE_SIZE)
            for message in page:
                if await ingest_message(state, message):
                    ingested += 1
            if cursor is None or cursor <= after:
                break
            after = cursor
    return ingested


async def ingest_message(state: ReplicaState, message: NodeMessage) -> bool:
    """Persist one message from the node, unless the store already holds it. Answers whether it landed
    as a new row: a message the store has under its node id, and the node's copy of a message this
    store imported, both leave the conversation as it is."""
    node_id = message["id"]
    if await asyncio.to_thread(state.store.has_node_id, node_id):
        return False
    room = message["room"]
    if "origin_id" in message and room == direct_room_id(state.agent):
        local_id = await asyncio.to_thread(state.store.local_id_for_origin, room, message["origin_id"])
        if local_id is not None:
            await asyncio.to_thread(state.store.mark_node_id, local_id, node_id)
            return False
    metas = await _pull_attachments(state, message)
    event: StoredEvent = {
        "type": message["type"],
        "ts": message["ts"],
        "text": message["text"],
        "room": room,
        "sender": message["sender"],
        "node_id": node_id,
    }
    if "input_method" in message:
        event["input_method"] = message["input_method"]
    if metas:
        event["attachments"] = metas
    await asyncio.to_thread(state.store.append, event)
    if message["sender"] != state.agent:
        await _notify(state, event, metas)
    return True


async def apply_room_event(state: ReplicaState, frame: dict[str, JsonValue]) -> None:
    """One live frame that is not a message: the rooms this agent joined or lost, and the floor the
    user just gave back."""
    kind = frame["type"]
    if "room" not in frame:
        raise NodeError(f"{kind} carries no room")
    room = frame["room"]
    if kind == _ROOM_CREATED:
        await asyncio.to_thread(state.store.upsert_room, parse_room(room))
        return
    if not isinstance(room, str):
        raise NodeError(f"{kind} carries no room id")
    if kind == _ROOM_DELETED:
        await asyncio.to_thread(state.store.delete_room, room)
        return
    fields, interrupt, reply_command = notifications.turn_end_notification(room)
    await _emit(state, _USER_FINISHED_TALKING, fields, interrupt, reply_command)


async def run_replica(state: ReplicaState, shutdown: asyncio.Event) -> None:
    """Hold the node's live edge for as long as the daemon runs. Each attempt opens the socket, pulls
    every room forward from the ids the store holds, then reads frames until the socket ends; frames
    that arrive during the pull wait in the socket's queue, so no message falls between the two. A
    connection that lasted past its pull starts the next backoff over."""
    backoff = REPLICA_RECONNECT_BASE_SECS
    while not shutdown.is_set():
        settled = False
        try:
            async with state.client.ws_connect() as socket:
                state.connected = True
                await catch_up(state)
                settled = True
                await _read_frames(state, socket, shutdown)
        except (NodeError, aiohttp.ClientError, OSError, sqlite3.Error) as exc:
            logger.warning("replica connection ended: %s", exc)
        finally:
            state.connected = False
        if settled:
            backoff = REPLICA_RECONNECT_BASE_SECS
        await _wait_out(shutdown, backoff)
        backoff = min(backoff * 2, REPLICA_RECONNECT_MAX_SECS)


async def _read_frames(state: ReplicaState, socket: aiohttp.ClientWebSocketResponse, shutdown: asyncio.Event) -> None:
    async for frame in socket:
        if frame.type is not aiohttp.WSMsgType.TEXT:
            return
        await _apply_frame(state, frame.data)
        if shutdown.is_set():
            return


async def _apply_frame(state: ReplicaState, raw: str) -> None:
    """One frame off the socket. A frame this client cannot read is dropped and logged rather than
    ending the connection, so an added field or an unknown event costs nothing."""
    try:
        frame = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("the node sent an unreadable frame")
        return
    if not isinstance(frame, dict) or "type" not in frame:
        return
    try:
        if frame["type"] in _ROOM_EVENTS:
            await apply_room_event(state, frame)
            return
        await ingest_message(state, parse_message(frame))
    except NodeError as exc:
        logger.warning("dropping a frame from the node: %s", exc)


async def _wait_out(shutdown: asyncio.Event, seconds: float) -> None:
    """Sleep the backoff, or stop early when the daemon is going down."""
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)


async def _pull_attachments(state: ReplicaState, message: NodeMessage) -> list[AttachmentMeta]:
    """Bring every attachment the message carries into the local store under the node's own id, so the
    notification names a path the agent opens and `chat attachments list` sees the file. One that
    cannot be fetched is logged and left off the message rather than stored as a broken reference."""
    if "attachments" not in message:
        return []
    landed: list[AttachmentMeta] = []
    for meta in message["attachments"]:
        blob = await asyncio.to_thread(attachments.blob_destination, state.attachments_root, meta)
        try:
            await state.client.download(meta["id"], blob)
        except (NodeError, OSError) as exc:
            logger.error("could not fetch attachment %s: %s", meta["id"], exc)
            continue
        landed.append(await asyncio.to_thread(attachments.record_meta, state.attachments_root, meta))
    return landed


async def _notify(state: ReplicaState, event: StoredEvent, metas: list[AttachmentMeta]) -> None:
    room = await asyncio.to_thread(state.store.room, event["room"])
    line = notifications.render_attachment_line(state.attachments_root, metas) if metas else None
    fields, interrupt, reply_command = notifications.message_notification(room, state.agent, event, line)
    await _emit(state, _MESSAGE_NOTIFICATION, fields, interrupt, reply_command)


async def _emit(state: ReplicaState, type_: str, fields: dict[str, JsonValue], interrupt: bool, reply_command: str) -> None:
    """Write the notification file. The message is already durable, so a failed write is news to log,
    never a reason to drop the connection."""
    try:
        await asyncio.to_thread(
            notifications.emit_notification, state.notifications_dir, type_, fields, interrupt=interrupt, reply_command=reply_command
        )
    except OSError as exc:
        logger.error("failed to write the chat %s notification: %s", type_, exc)
