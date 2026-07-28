import json
import pathlib

from slack_cli.notif import SlackMessageEvent, build_notification, humanize_mentions, write_notification

BOT_USER_ID = "UBOT"
USER_NAMES = {"U1": "elio", "U2": "sam", BOT_USER_ID: "vesta"}


def resolve_user(user_id: str) -> str:
    return USER_NAMES[user_id] if user_id in USER_NAMES else user_id


def resolve_channel(channel_id: str) -> str:
    return "general"


def build(**overrides: str) -> dict[str, str | bool] | None:
    fields = {
        "type": "message",
        "user": "U1",
        "text": "hello",
        "channel": "D123",
        "channel_type": "im",
        "ts": "1751970000.000100",
    } | overrides
    event = SlackMessageEvent.model_validate(fields)
    return build_notification(event, bot_user_id=BOT_USER_ID, resolve_user=resolve_user, resolve_channel=resolve_channel)


def test_dm_interrupts_by_default() -> None:
    assert build() == {
        "source": "slack",
        "type": "message",
        "timestamp": "2025-07-08T10:20:00.000100+00:00",
        "message": "hello",
        "sender": "elio",
        "sender_id": "U1",
        "channel_id": "D123",
        "message_ts": "1751970000.000100",
    }


def test_ambient_channel_message_pools() -> None:
    notif = build(channel="C9", channel_type="channel")
    assert notif is not None
    assert notif["interrupt"] is False
    assert notif["channel_name"] == "#general"
    assert "mention" not in notif


def test_channel_mention_interrupts_and_is_humanized() -> None:
    notif = build(channel="C9", channel_type="channel", text="hey <@UBOT>, ask <@U2>")
    assert notif is not None
    assert notif["mention"] is True
    assert "interrupt" not in notif
    assert notif["message"] == "hey @vesta, ask @sam"


def test_group_dm_interrupts_without_mention() -> None:
    notif = build(channel="G7", channel_type="mpim")
    assert notif is not None
    assert "interrupt" not in notif
    assert notif["channel_name"] == "#general"


def test_thread_ts_is_carried() -> None:
    notif = build(thread_ts="1751960000.000200")
    assert notif is not None
    assert notif["thread_ts"] == "1751960000.000200"


def test_own_message_is_skipped() -> None:
    assert build(user=BOT_USER_ID) is None


def test_bot_message_is_skipped() -> None:
    assert build(bot_id="B44") is None


def test_subtype_is_skipped() -> None:
    assert build(subtype="message_changed") is None


def test_humanize_mentions_leaves_unknown_ids_readable() -> None:
    assert humanize_mentions("ping <@U404>", resolve_user) == "ping @U404"


def test_write_notification_creates_json_file(tmp_path: pathlib.Path) -> None:
    notif = build()
    assert notif is not None
    path = write_notification(tmp_path / "notifications", notif)
    assert path.name.endswith("-slack-message.json")
    assert json.loads(path.read_text()) == notif
    assert list(path.parent.glob("*.tmp")) == []
