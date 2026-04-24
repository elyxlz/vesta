"""Tests for notification loading, parsing, batching, deletion, and monitor loop."""

import asyncio
import datetime as dt
import json
from unittest.mock import AsyncMock, patch

import pytest
import core.models as vm
from core.loops import (
    _is_new_json,
    _load_notification_files,
    delete_notification_files,
    format_notification_batch,
    load_notifications,
    load_new_notifications,
    process_batch,
)


# --- _load_notification_files ---


def test_load_files_nonexistent_dir(tmp_path):
    assert _load_notification_files(tmp_path / "does-not-exist") == []


def test_load_files_empty_dir(tmp_path):
    d = tmp_path / "notifications"
    d.mkdir()
    assert _load_notification_files(d) == []


def test_load_files_only_json(tmp_path):
    d = tmp_path / "notifications"
    d.mkdir()
    (d / "valid.json").write_text('{"a":1}')
    (d / "readme.txt").write_text("ignore me")
    (d / "data.log").write_text("also ignore")
    result = _load_notification_files(d)
    assert len(result) == 1
    assert result[0][0].name == "valid.json"


def test_load_files_multiple(tmp_path):
    d = tmp_path / "notifications"
    d.mkdir()
    for i in range(3):
        (d / f"notif-{i}.json").write_text(f'{{"n":{i}}}')
    assert len(_load_notification_files(d)) == 3


# --- load_notifications ---


VALID_NOTIF = json.dumps({"timestamp": "2025-01-01T00:00:00", "source": "test", "type": "message"})


@pytest.mark.parametrize(
    "content,should_parse",
    [
        (VALID_NOTIF, True),
        (json.dumps({"timestamp": "2025-01-01T00:00:00", "source": "test", "type": "msg", "extra": "field"}), True),
        ("not json at all", False),
        (json.dumps({"source": "test", "type": "msg"}), False),  # missing timestamp
        ("{}", False),  # missing required fields
    ],
    ids=["valid", "extra-fields", "bad-json", "missing-timestamp", "empty-object"],
)
@pytest.mark.anyio
async def test_load_notifications_parsing(tmp_path, content, should_parse):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    (config.notifications_dir / "test.json").write_text(content)

    result = await load_notifications(config=config)

    if should_parse:
        assert len(result) == 1
        assert result[0].source == "test"
    else:
        assert len(result) == 0


@pytest.mark.anyio
async def test_load_notifications_deletes_bad_files(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    bad_file = config.notifications_dir / "bad.json"
    bad_file.write_text("not json")

    await load_notifications(config=config)

    assert not bad_file.exists(), "bad notification file should be deleted"


@pytest.mark.anyio
async def test_load_notifications_partial_success(tmp_path):
    """Mix of valid and invalid files: valid ones parse, invalid ones are deleted."""
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    (config.notifications_dir / "good.json").write_text(VALID_NOTIF)
    bad_file = config.notifications_dir / "bad.json"
    bad_file.write_text("broken")

    result = await load_notifications(config=config)
    assert len(result) == 1
    assert not bad_file.exists()


# --- delete_notification_files ---


@pytest.mark.anyio
async def test_delete_notification_files(tmp_path):
    f1 = tmp_path / "a.json"
    f2 = tmp_path / "b.json"
    f1.write_text("x")
    f2.write_text("y")

    notifs = [
        vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="t", type="m", file_path=str(f1)),
        vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="t", type="m", file_path=str(f2)),
    ]
    await delete_notification_files(notifs)

    assert not f1.exists()
    assert not f2.exists()


@pytest.mark.anyio
async def test_delete_ignores_none_paths():
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="t", type="m")
    assert notif.file_path is None
    await delete_notification_files([notif])  # should not raise


@pytest.mark.anyio
async def test_delete_handles_already_deleted(tmp_path):
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="t", type="m", file_path=str(tmp_path / "gone.json"))
    await delete_notification_files([notif])  # missing_ok=True, should not raise


# --- format_notification_batch ---


def test_batch_single():
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message")
    formatted = format_notification_batch([notif])
    assert "[NOTIFICATIONS]" not in formatted
    assert "[message from test]" in formatted


def test_batch_multiple():
    notifs = [
        vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message"),
        vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 1), source="test", type="alert"),
    ]
    formatted = format_notification_batch(notifs)
    assert "[NOTIFICATIONS]" in formatted
    assert "[message from test]" in formatted
    assert "[alert from test]" in formatted


def test_batch_with_suffix():
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message")
    formatted = format_notification_batch([notif], suffix="Check later")
    assert "Check later" in formatted


def test_notification_format_for_display():
    notif = vm.Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "email", "type": "message", "sender": "alice"})
    display = notif.format_for_display()
    assert "[message from email]" in display
    assert "sender=alice" in display


def test_format_for_display_drops_empty_and_false_fields():
    """Empty strings, False bools, empty lists, and None should not appear in context."""
    notif = vm.Notification.model_validate({
        "timestamp": "2025-01-01T00:00:00",
        "source": "whatsapp",
        "type": "message",
        "contact_name": "Alice",
        "message": "hi",
        "chat_name": "",
        "media_type": "",
        "is_forwarded": False,
        "quoted_text": None,
        "tags": [],
        "contact_unknown": True,
    })
    display = notif.format_for_display()
    assert "contact_name=Alice" in display
    assert "message=hi" in display
    assert "contact_unknown=True" in display  # True bool kept (interesting case)
    assert "chat_name=" not in display
    assert "media_type=" not in display
    assert "is_forwarded" not in display
    assert "quoted_text" not in display
    assert "tags" not in display


def test_format_for_display_strips_timestamp_microseconds():
    notif = vm.Notification.model_validate({
        "timestamp": "2025-01-01T12:34:56.123456+00:00",
        "source": "tasks",
        "type": "reminder",
        "message": "ping",
    })
    display = notif.format_for_display()
    assert ".123456" not in display
    assert "timestamp=2025-01-01T12:34:56+00:00" in display


@pytest.mark.parametrize(
    "payload,expected_substr",
    [
        (
            {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "contact_name": "Alice", "message": "hi"},
            "whatsapp send --to 'Alice'",
        ),
        (
            {
                "timestamp": "2025-01-01T00:00:00",
                "source": "whatsapp",
                "type": "message",
                "chat_name": "Group",
                "sender": "bob",
                "message": "hi",
            },
            "whatsapp send --to 'Group'",
        ),
        (
            {"timestamp": "2025-01-01T00:00:00", "source": "telegram", "type": "message", "contact_name": "Carol", "message": "hi"},
            "telegram send 'Carol'",
        ),
        (
            {"timestamp": "2025-01-01T00:00:00", "source": "app-chat", "type": "message", "message": "hi"},
            "app-chat send --message",
        ),
    ],
    ids=["whatsapp-direct", "whatsapp-group", "telegram-direct", "app-chat"],
)
def test_batch_includes_reply_hint(payload, expected_substr):
    notif = vm.Notification.model_validate(payload)
    formatted = format_notification_batch([notif])
    assert "→ Reply with:" in formatted
    assert expected_substr in formatted


def test_batch_no_hint_for_unknown_source():
    notif = vm.Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "email", "type": "message", "sender": "alice"})
    formatted = format_notification_batch([notif])
    assert "→ Reply with:" not in formatted


def test_batch_no_hint_for_non_message_type():
    notif = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "reaction", "contact_name": "Alice", "emoji": "👍"}
    )
    formatted = format_notification_batch([notif])
    assert "→ Reply with:" not in formatted


# --- load_new_notifications ---


@pytest.mark.anyio
async def test_load_new_notifications_emits_events(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    (config.notifications_dir / "n.json").write_text(VALID_NOTIF)

    state = vm.State()
    q = state.event_bus.subscribe()

    result = await load_new_notifications(state=state, config=config)
    assert len(result) == 1

    event = q.get_nowait()
    assert event["type"] == "notification"
    assert event["source"] == "test"


# --- process_batch ---


@pytest.mark.anyio
async def test_process_batch_queues_prompt(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    queue: asyncio.Queue = asyncio.Queue()

    f = tmp_path / "n.json"
    f.write_text("x")
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message", file_path=str(f))

    with patch("core.loops.load_prompt", return_value=""), patch("core.loops.attempt_interrupt", new_callable=AsyncMock):
        await process_batch([notif], queue=queue, state=state, config=config)

    assert not queue.empty()
    prompt, is_user = await queue.get()
    assert "[message from test]" in prompt
    assert is_user is False


@pytest.mark.anyio
async def test_process_batch_empty_is_noop():
    config = vm.VestaConfig()
    state = vm.State()
    queue: asyncio.Queue = asyncio.Queue()

    await process_batch([], queue=queue, state=state, config=config)
    assert queue.empty()


@pytest.mark.anyio
async def test_process_batch_deletes_files(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    queue: asyncio.Queue = asyncio.Queue()

    f = tmp_path / "to-delete.json"
    f.write_text("x")
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="t", type="m", file_path=str(f))

    with patch("core.loops.load_prompt", return_value=""):
        await process_batch([notif], queue=queue, state=state, config=config)

    assert not f.exists(), "notification file should be deleted after processing"


# --- _is_new_json ---


@pytest.mark.parametrize(
    "change_val,path,expected",
    [
        (1, "/foo/bar.json", True),  # Change.added
        (2, "/foo/bar.json", True),  # Change.modified
        (3, "/foo/bar.json", False),  # Change.deleted
        (1, "/foo/bar.txt", False),
        (1, "/foo/bar.JSON", False),  # case-sensitive
    ],
    ids=["added-json", "modified-json", "deleted-json", "added-txt", "uppercase-extension"],
)
def test_is_new_json(change_val, path, expected):
    from watchfiles import Change

    change = Change(change_val)
    assert _is_new_json(change, path) is expected
