"""The one writer of the chat skill's notifications: the envelope the monitor loop reads, the fields a
message carries about its room and its sender, and the turn-end re-wake. Every chat notification is
written here, so the shape the model receives has a single owner. Fields are scalars, since the model
reads them as attribute text."""

import datetime as dt
import json
import pathlib as pl
import time
import typing as tp

from .attachments import AttachmentMeta, human_size
from .node_client import JsonValue
from .store import RoomRecord, StoredEvent, direct_room_id

SOURCE = "chat"
# The reply the direct room takes: it is the conversation `chat send` writes into by default.
DIRECT_REPLY_COMMAND = "chat send --message -"
REPLY_HINT = "think about how you can best show your personality"
FETCH_FAILURE = "could not be fetched from the node"
TURN_END_MESSAGE = "the user finished talking; a reply of yours was refused mid-turn and dropped. Answer their whole thought fresh now"


def render_attachment_line(attachments_root: pl.Path, metas: list[AttachmentMeta], unfetched: tp.AbstractSet[str] | None = None) -> str:
    """One scalar the notification renderer shows as an attribute: name, type, human size, and the
    absolute path the agent opens directly. A file named in `unfetched` never reached this store, so it
    is named with the reason instead of a path the agent would find empty. Paths derive from the metas
    in hand: no disk reads here."""
    missing = unfetched if unfetched is not None else frozenset()
    parts = []
    for meta in metas:
        described = f"{meta['name']} ({meta['mime']}, {human_size(meta['size'])})"
        blob = attachments_root / meta["id"] / meta["name"]
        parts.append(f"{described} {FETCH_FAILURE}" if meta["id"] in missing else f"{described} at {blob}")
    return "; ".join(parts)


def emit_notification(notifications_dir: pl.Path, type_: str, fields: dict[str, JsonValue], *, interrupt: bool, reply_command: str) -> None:
    """Write one notification file: envelope basics, the time-ns filename, and the atomic tmp+replace,
    shared by every notification this skill emits."""
    notifications_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, JsonValue] = {
        "timestamp": dt.datetime.now().isoformat(),
        "source": SOURCE,
        "type": type_,
        "interrupt": interrupt,
        "reply_command": reply_command,
        **fields,
    }
    path = notifications_dir / f"{time.time_ns()}-chat-{type_}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload))
    tmp.replace(path)


def reply_command(room: str, agent: str) -> str:
    """How to answer in a room: the direct conversation takes the bare send, every other room is
    addressed by its id. Every notification this skill writes takes its command from here."""
    return DIRECT_REPLY_COMMAND if room == direct_room_id(agent) else f"chat send --room {room} --message -"


def _room_name(store_room: RoomRecord | None, agent: str, direct: bool) -> str | None:
    """What the room is called: a group's name, the peer's name in a peer room, nothing in the direct
    room (the agent is already in it) or while the store does not hold the room yet."""
    if direct or store_room is None:
        return None
    if store_room["name"] is not None:
        return store_room["name"]
    others = [member for member in store_room["agents"] if member != agent]
    return others[0] if len(others) == 1 else None


def message_notification(
    store_room: RoomRecord | None, agent: str, message: StoredEvent, attachment_line: str | None
) -> tuple[dict[str, JsonValue], bool, str]:
    """The fields, the interrupt decision and the reply command for one replicated message. The user
    interrupts the agent's work; another agent waits for the next idle gap."""
    room = message["room"]
    direct = room == direct_room_id(agent)
    sender = message["sender"] if "sender" in message and message["sender"] is not None else ""
    fields: dict[str, JsonValue] = {"room": room, "sender": sender}
    name = _room_name(store_room, agent, direct)
    if name is not None:
        fields["room_name"] = name
    if store_room is not None:
        fields["members"] = ", ".join(store_room["agents"])
    fields["message"] = message["text"]
    if attachment_line is not None:
        fields["attachments"] = attachment_line
    if direct:
        fields["reply_hint"] = REPLY_HINT
    return fields, sender == "user", reply_command(room, agent)


def turn_end_notification(room: str, agent: str) -> tuple[dict[str, JsonValue], bool, str]:
    """The re-wake behind the send gate: a refused reply was dropped by the model on the promise that a
    notification follows the turn, so the floor clearing delivers one even when the turn itself produced
    no message. It names the room to answer in, whichever room the user was talking into."""
    return {"room": room, "message": TURN_END_MESSAGE}, True, reply_command(room, agent)
