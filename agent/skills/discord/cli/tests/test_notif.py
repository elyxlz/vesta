import datetime as dt
import json
import pathlib

from discord_cli.notif import MessageFacts, build_notification, write_notification

TIMESTAMP = dt.datetime(2026, 7, 8, 10, 20, tzinfo=dt.UTC)


def facts(**overrides: str | bool | None) -> MessageFacts:
    fields: dict[str, str | bool | dt.datetime | None] = {
        "content": "hello",
        "author_name": "elio",
        "author_id": "42",
        "author_is_self": False,
        "author_is_bot": False,
        "channel_id": "100",
        "channel_name": None,
        "server": None,
        "is_dm": True,
        "mentions_me": False,
        "message_id": "900",
        "timestamp": TIMESTAMP,
    }
    return MessageFacts.model_validate(fields | dict(overrides))


def test_dm_interrupts_by_default() -> None:
    assert build_notification(facts()) == {
        "source": "discord",
        "type": "message",
        "timestamp": "2026-07-08T10:20:00+00:00",
        "message": "hello",
        "sender": "elio",
        "sender_id": "42",
        "channel_id": "100",
        "message_id": "900",
    }


def test_ambient_server_message_pools() -> None:
    notif = build_notification(facts(is_dm=False, channel_name="#general", server="friends"))
    assert notif is not None
    assert notif["interrupt"] is False
    assert notif["channel_name"] == "#general"
    assert notif["server"] == "friends"


def test_server_mention_interrupts() -> None:
    notif = build_notification(facts(is_dm=False, channel_name="#general", server="friends", mentions_me=True))
    assert notif is not None
    assert notif["mention"] is True
    assert "interrupt" not in notif


def test_own_message_is_skipped() -> None:
    assert build_notification(facts(author_is_self=True)) is None


def test_other_bot_message_is_flagged() -> None:
    notif = build_notification(facts(author_is_bot=True))
    assert notif is not None
    assert notif["from_bot"] is True


def test_write_notification_creates_json_file(tmp_path: pathlib.Path) -> None:
    notif = build_notification(facts())
    assert notif is not None
    path = write_notification(tmp_path / "notifications", notif)
    assert path.name.endswith("-discord-message.json")
    assert json.loads(path.read_text()) == notif
    assert list(path.parent.glob("*.tmp")) == []
