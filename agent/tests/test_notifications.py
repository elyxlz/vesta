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
    _notification_watcher,
    delete_notification_files,
    format_notification_batch,
    load_notifications,
    monitor_loop,
    process_batch,
)
from wait_util import wait_for_condition


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
    assert "<notifications>" in formatted
    assert '<notification source="test" type="message">' in formatted
    assert "</notifications>" in formatted


def test_batch_multiple():
    notifs = [
        vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message"),
        vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 1), source="test", type="alert"),
    ]
    formatted = format_notification_batch(notifs)
    assert formatted.count("<notification ") == 2
    assert '<notification source="test" type="message">' in formatted
    assert '<notification source="test" type="alert">' in formatted
    assert formatted.startswith("<notifications>\n")
    assert formatted.endswith("</notifications>")


def test_batch_with_suffix():
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message")
    formatted = format_notification_batch([notif], suffix="Check later")
    assert "Check later" in formatted


def test_notification_format_for_display():
    notif = vm.Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "email", "type": "message", "sender": "alice"})
    display = notif.format_for_display()
    assert display.startswith('<notification source="email" type="message">')
    assert display.endswith("</notification>")
    assert "sender=alice" in display


def test_format_for_display_drops_empty_and_false_fields():
    """Empty strings, False bools, empty lists, and None should not appear in context."""
    notif = vm.Notification.model_validate(
        {
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
        }
    )
    display = notif.format_for_display()
    assert "contact_name=Alice" in display
    assert "message=hi" in display
    assert "contact_unknown=True" in display  # True bool kept (interesting case)
    assert "chat_name=" not in display
    assert "media_type=" not in display
    assert "is_forwarded" not in display
    assert "quoted_text" not in display
    assert "tags" not in display


def test_format_for_display_keeps_integer_zero():
    """Integer 0 is falsey but meaningful (e.g. minutes_until=0 for a reminder firing now)."""
    notif = vm.Notification.model_validate(
        {
            "timestamp": "2025-01-01T00:00:00",
            "source": "microsoft",
            "type": "calendar",
            "subject": "Now",
            "minutes_until": 0,
        }
    )
    display = notif.format_for_display()
    assert "minutes_until=0" in display


def test_format_for_display_strips_timestamp_microseconds():
    notif = vm.Notification.model_validate(
        {
            "timestamp": "2025-01-01T12:34:56.123456+00:00",
            "source": "tasks",
            "type": "reminder",
            "message": "ping",
        }
    )
    display = notif.format_for_display()
    assert ".123456" not in display
    assert "timestamp=2025-01-01T12:34:56+00:00" in display


@pytest.mark.parametrize(
    "payload,expected_substr",
    [
        (
            {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "message", "contact_name": "Alice", "message": "hi"},
            "Reply using the `whatsapp` skill",
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
            "Reply using the `whatsapp` skill",
        ),
        (
            {"timestamp": "2025-01-01T00:00:00", "source": "telegram", "type": "message", "contact_name": "Carol", "message": "hi"},
            "Reply using the `telegram` skill",
        ),
        (
            {"timestamp": "2025-01-01T00:00:00", "source": "app-chat", "type": "message", "message": "hi"},
            "Reply using the `app-chat` skill",
        ),
    ],
    ids=["whatsapp-direct", "whatsapp-group", "telegram-direct", "app-chat"],
)
def test_batch_includes_reply_hint(payload, expected_substr):
    notif = vm.Notification.model_validate(payload)
    formatted = format_notification_batch([notif])
    assert "→ Reply using" in formatted
    assert expected_substr in formatted


def test_batch_no_hint_for_unknown_source():
    notif = vm.Notification.model_validate({"timestamp": "2025-01-01T00:00:00", "source": "email", "type": "message", "sender": "alice"})
    formatted = format_notification_batch([notif])
    assert "→ Reply using" not in formatted


def test_batch_no_hint_for_non_message_type():
    notif = vm.Notification.model_validate(
        {"timestamp": "2025-01-01T00:00:00", "source": "whatsapp", "type": "reaction", "contact_name": "Alice", "emoji": "👍"}
    )
    formatted = format_notification_batch([notif])
    assert "→ Reply using" not in formatted


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
    prompt, is_user, file_paths = await queue.get()
    assert '<notification source="test" type="message">' in prompt
    assert is_user is False


@pytest.mark.anyio
async def test_process_batch_empty_is_noop():
    config = vm.VestaConfig()
    state = vm.State()
    queue: asyncio.Queue = asyncio.Queue()

    await process_batch([], queue=queue, state=state, config=config)
    assert queue.empty()


@pytest.mark.anyio
async def test_process_batch_keeps_files_until_processing(tmp_path):
    """process_batch must NOT delete files at enqueue time; files stay on disk until the message
    is fully processed so that a mid-compaction restart can recover unprocessed notifications."""
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    queue: asyncio.Queue = asyncio.Queue()

    f = tmp_path / "to-keep.json"
    f.write_text("x")
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="t", type="m", file_path=str(f))

    with patch("core.loops.load_prompt", return_value=""):
        await process_batch([notif], queue=queue, state=state, config=config)

    assert f.exists(), "notification file must stay on disk until the queued message is processed"
    _, _, file_paths = await queue.get()
    assert str(f) in file_paths, "file path is carried in the queue item for deferred deletion"


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


# --- monitor_loop routing ---


def _passive_config(tmp_path):
    """Config that disables proactive/dreamer side effects so monitor_loop only does notification routing."""
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    config.ephemeral = True  # no dreamer drops
    return config


def _write_notif(directory, stem, *, interrupt, source="test", type_="message"):
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source=source, type=type_, interrupt=interrupt, body="hi")
    path = directory / f"{stem}.json"
    path.write_text(notif.model_dump_json())
    return path


async def _run_monitor(queue, *, state, config):
    """Start monitor_loop as a task with load_prompt stubbed so external batches do not read disk prompts."""
    with patch("core.loops.load_prompt", return_value=""):
        task = asyncio.create_task(monitor_loop(queue, state=state, config=config))
        try:
            yield task
        finally:
            state.shutdown_event.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
async def test_monitor_loop_interrupt_queued_while_not_idle(tmp_path):
    """An interrupt:true notification is queued immediately even when the bus is not idle."""
    config = _passive_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.event_bus.set_state("thinking")  # explicitly NOT idle
    queue: asyncio.Queue = asyncio.Queue()

    runner = _run_monitor(queue, state=state, config=config)
    await runner.__anext__()
    try:
        _write_notif(config.notifications_dir, "urgent", interrupt=True)
        await wait_for_condition(lambda: not queue.empty(), message="interrupt notification was never queued")

        prompt, is_user, file_paths = await queue.get()
        assert '<notification source="test" type="message">' in prompt
        assert is_user is False
        assert state.event_bus.state == "thinking", "interrupt routing must not depend on idle state"
    finally:
        await runner.aclose()


@pytest.mark.anyio
async def test_monitor_loop_passive_held_until_idle_then_flushed_once(tmp_path):
    """A passive notification is held while the bus is not idle, then flushed exactly once on idle."""
    config = _passive_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.event_bus.set_state("thinking")  # held while busy
    queue: asyncio.Queue = asyncio.Queue()

    runner = _run_monitor(queue, state=state, config=config)
    await runner.__anext__()
    try:
        path = _write_notif(config.notifications_dir, "passive", interrupt=False)

        # While not idle, the passive notification must stay on disk and not be queued.
        await wait_for_condition(lambda: not path.exists() or queue.qsize() == 0)
        assert queue.empty(), "passive notification must not be queued while bus is not idle"
        assert path.exists(), "passive file stays on disk until the batch flushes"

        # Flip to idle; the held batch flushes on the next tick.
        state.event_bus.set_state("idle")
        await wait_for_condition(lambda: not queue.empty(), message="passive batch never flushed after idle")

        prompt, is_user, file_paths = await queue.get()
        assert '<notification source="test" type="message">' in prompt
        assert is_user is False

        # Exactly once: file stays on disk (deleted only after processing), but nothing re-queues.
        await asyncio.sleep(0.05)
        assert queue.empty(), "passive batch must flush exactly once"
        assert path.exists(), "file stays on disk until _run_messages_with_interrupts deletes it after processing"
    finally:
        await runner.aclose()


@pytest.mark.anyio
async def test_monitor_loop_passive_not_double_queued_across_ticks(tmp_path):
    """A passive file seen on one tick is not re-queued on a later tick (queued_paths dedup)."""
    config = _passive_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.event_bus.set_state("thinking")  # keep passive batch pending across ticks
    queue: asyncio.Queue = asyncio.Queue()

    notify_taps: list[None] = []
    real_load = load_notifications

    async def counting_load(*, config):
        notify_taps.append(None)
        return await real_load(config=config)

    runner = _run_monitor(queue, state=state, config=config)
    await runner.__anext__()
    try:
        with patch("core.loops.load_notifications", counting_load):
            path = _write_notif(config.notifications_dir, "dup", interrupt=False)
            # Wait for the loader to observe the file across at least two ticks while held (not idle).
            await wait_for_condition(lambda: len(notify_taps) >= 2, message="monitor_loop did not tick twice")
            assert queue.empty(), "held passive file must not be queued while not idle"

            state.event_bus.set_state("idle")
            await wait_for_condition(lambda: not queue.empty(), message="passive batch never flushed")
            await asyncio.sleep(0.05)

            # Despite being observed on multiple ticks, the file produces a single queued batch.
            # File stays on disk (deleted only after processing), but queued_paths dedup prevents re-queueing.
            assert queue.qsize() == 1, f"passive file must be queued once, got {queue.qsize()}"
            assert path.exists(), "file stays on disk until _run_messages_with_interrupts deletes it after processing"
    finally:
        await runner.aclose()


@pytest.mark.anyio
async def test_monitor_loop_emits_each_notification_once_across_ticks(tmp_path):
    """A persisted file re-read every tick must emit a single 'notification' event, not one
    per tick. Files kept on disk (e.g. deferred while unauthenticated) re-emitting every 2s
    tick was the notification storm: 16 kept files -> ~8 db rows/sec, 3.6M rows."""
    config = _passive_config(tmp_path)
    config.monitor_tick_interval = 1
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.event_bus.set_state("thinking")  # hold the passive file on disk across ticks
    queue: asyncio.Queue = asyncio.Queue()
    sub = state.event_bus.subscribe()

    ticks = [0]
    real_load = load_notifications

    async def counting_load(*, config):
        ticks[0] += 1
        return await real_load(config=config)

    runner = _run_monitor(queue, state=state, config=config)
    await runner.__anext__()
    try:
        with patch("core.loops.load_notifications", counting_load):
            _write_notif(config.notifications_dir, "kept", interrupt=False)
            await wait_for_condition(lambda: ticks[0] >= 3, message="monitor_loop did not re-read across ticks")

        emitted = [sub.get_nowait() for _ in range(sub.qsize())]
        notifs = [e for e in emitted if e["type"] == "notification"]
        assert len(notifs) == 1, f"each notification must emit exactly once, got {len(notifs)} across {ticks[0]} ticks"
    finally:
        await runner.aclose()


# --- _notification_watcher local-stop bridge ---


@pytest.mark.anyio
async def test_notification_watcher_signals_then_stops_on_shutdown(tmp_path):
    """The watcher fires `notify` on a new .json file and returns promptly when the shared shutdown event is set."""
    notifications_dir = tmp_path / "notifications"
    notifications_dir.mkdir(parents=True, exist_ok=True)
    notify = asyncio.Event()
    shutdown = asyncio.Event()

    task = asyncio.create_task(_notification_watcher(notify, notifications_dir=notifications_dir, shutdown=shutdown))
    try:
        # awatch needs a moment to install its filesystem watch before changes register.
        await asyncio.sleep(0.2)
        (notifications_dir / "new.json").write_text('{"x": 1}')
        await wait_for_condition(notify.is_set, message="watcher never signalled notify on a new .json file")

        # Setting the SHARED shutdown event must bridge into the watcher's local stop and end the coroutine.
        shutdown.set()
        await wait_for_condition(task.done, message="watcher did not stop after shutdown_event was set")
        await task  # must not raise
        # The bridge means awatch only ever touched its own local stop event; the shared one stays exactly as we set it.
        assert shutdown.is_set(), "watcher teardown must not clear the shared shutdown event"
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
