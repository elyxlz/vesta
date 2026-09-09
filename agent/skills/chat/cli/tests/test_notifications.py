"""Tests for the chat notification writer: the envelope every chat notification carries, the fields a
message notification names its room and sender with, and the turn-end re-wake."""

import json

from chat_cli import notifications
from chat_cli.store import RoomRecord, StoredEvent

AGENT = "vesta"
DIRECT_ROOM: RoomRecord = {"id": "dm:vesta", "name": None, "agents": ["vesta"]}
GROUP_ROOM: RoomRecord = {"id": "grp-7", "name": "planning", "agents": ["bob", "vesta"]}
PEER_ROOM: RoomRecord = {"id": "dm:bob:vesta", "name": None, "agents": ["bob", "vesta"]}


def _message(room: str, sender: str, text: str) -> StoredEvent:
    kind = "user" if sender == "user" else "chat"
    return {"type": kind, "ts": "2026-09-05T10:00:00+00:00", "text": text, "room": room, "sender": sender}


def _written(notifications_dir, type_: str) -> dict[str, object]:
    paths = sorted(notifications_dir.glob(f"*-chat-{type_}.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text())


def test_a_user_message_in_the_direct_room_interrupts_and_replies_without_a_room(tmp_path):
    fields, interrupt, reply_command = notifications.message_notification(
        DIRECT_ROOM, AGENT, _message("dm:vesta", "user", "are you there"), None
    )
    notifications.emit_notification(tmp_path, "message", fields, interrupt=interrupt, reply_command=reply_command)

    written = _written(tmp_path, "message")
    written.pop("timestamp")
    assert written == {
        "source": "chat",
        "type": "message",
        "interrupt": True,
        "reply_command": "chat send --message -",
        "room": "dm:vesta",
        "sender": "user",
        "members": "vesta",
        "message": "are you there",
        "reply_hint": "think about how you can best show your personality",
    }


def test_an_agent_message_in_a_group_waits_for_idle_and_names_the_room(tmp_path):
    fields, interrupt, reply_command = notifications.message_notification(GROUP_ROOM, AGENT, _message("grp-7", "bob", "shipping tonight"), None)
    notifications.emit_notification(tmp_path, "message", fields, interrupt=interrupt, reply_command=reply_command)

    written = _written(tmp_path, "message")
    written.pop("timestamp")
    assert written == {
        "source": "chat",
        "type": "message",
        "interrupt": False,
        "reply_command": "chat send --room grp-7 --message -",
        "room": "grp-7",
        "room_name": "planning",
        "sender": "bob",
        "members": "bob, vesta",
        "message": "shipping tonight",
    }


def test_the_turn_end_notification_names_the_room_the_user_was_talking_in(tmp_path):
    fields, interrupt, reply_command = notifications.turn_end_notification("dm:vesta", AGENT)
    notifications.emit_notification(tmp_path, "user_finished_talking", fields, interrupt=interrupt, reply_command=reply_command)

    written = _written(tmp_path, "user_finished_talking")
    written.pop("timestamp")
    assert written == {
        "source": "chat",
        "type": "user_finished_talking",
        "interrupt": True,
        "reply_command": "chat send --message -",
        "room": "dm:vesta",
        "message": "the user finished talking; a reply of yours was refused mid-turn and dropped. Answer their whole thought fresh now",
    }


def test_a_turn_end_outside_the_direct_room_is_answered_by_room(tmp_path):
    _, _, reply_command = notifications.turn_end_notification("grp-7", AGENT)

    assert reply_command == "chat send --room grp-7 --message -"


def test_a_peer_room_carries_the_peer_as_its_name(tmp_path):
    fields, _, reply_command = notifications.message_notification(PEER_ROOM, AGENT, _message("dm:bob:vesta", "bob", "ping"), None)

    assert fields["room_name"] == "bob"
    assert fields["members"] == "bob, vesta"
    assert reply_command == "chat send --room dm:bob:vesta --message -"


def test_a_room_the_store_does_not_hold_yet_carries_neither_a_name_nor_members(tmp_path):
    fields, _, _ = notifications.message_notification(None, AGENT, _message("grp-9", "bob", "ping"), None)

    assert "room_name" not in fields
    assert "members" not in fields
    assert fields["room"] == "grp-9"


def test_an_attachment_line_rides_the_notification(tmp_path):
    line = notifications.render_attachment_line(
        tmp_path / "attachments", [{"id": "a" * 32, "name": "photo.jpg", "mime": "image/jpeg", "size": 13}]
    )
    fields, _, _ = notifications.message_notification(DIRECT_ROOM, AGENT, _message("dm:vesta", "user", "look"), line)

    assert fields["attachments"] == f"photo.jpg (image/jpeg, 13 B) at {tmp_path / 'attachments' / ('a' * 32) / 'photo.jpg'}"


def test_a_file_this_store_never_received_is_named_with_the_reason(tmp_path):
    meta = {"id": "a" * 32, "name": "photo.jpg", "mime": "image/jpeg", "size": 13}

    line = notifications.render_attachment_line(tmp_path / "attachments", [meta], {meta["id"]})

    assert line == "photo.jpg (image/jpeg, 13 B) could not be fetched from the node"


def test_the_writer_publishes_the_file_atomically(tmp_path):
    notifications.emit_notification(
        tmp_path / "notifications", "message", {"message": "hi"}, interrupt=True, reply_command="chat send --message -"
    )

    directory = tmp_path / "notifications"
    assert [path.suffix for path in sorted(directory.iterdir())] == [".json"]
    assert json.loads(next(iter(directory.iterdir())).read_text())["source"] == "chat"
