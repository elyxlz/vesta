"""Tests for nightly dreamer/memory scheduling."""

import asyncio
import datetime as dt
import json
import typing as tp
from unittest.mock import AsyncMock, patch

import pytest

import core.models as vm
from core.cc_sdk import ClaudeSDKClient, ClaudeSDKError


def _setup(tmp_path, *, dreamer_hour=4):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", nightly_memory_hour=dreamer_hour)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_drops_dream_notification(tmp_path):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    state = vm.State()
    fake_now = dt.datetime(2025, 6, 15, config.nightly_memory_hour, 0, 0)

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    files = list(config.notifications_dir.glob("nightly_dream-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text())
    assert payload["source"] == "core"
    assert payload["type"] == "nightly_dream"
    assert payload["body"] == "dreamer prompt"
    # Persisted last_dreamer_run is unchanged until the agent itself calls mark_dreamer_complete.
    assert state.persisted.last_dreamer_run is None


def test_skips_when_already_run_today(tmp_path):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    fake_now = dt.datetime(2025, 6, 15, config.nightly_memory_hour, 0, 0)

    state = vm.State()
    state.persisted.last_dreamer_run = fake_now

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert list(config.notifications_dir.glob("nightly_dream-*.json")) == []


def test_skips_before_dreamer_hour(tmp_path):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path, dreamer_hour=4)
    state = vm.State()
    earlier = dt.datetime(2025, 6, 15, 2, 0, 0)

    with (
        patch("core.loops._now", return_value=earlier),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert list(config.notifications_dir.glob("nightly_dream-*.json")) == []


def test_retries_after_dream_hour_when_not_done_today(tmp_path):
    """If the dream didn't complete (rate limit, crash) and the prior notification is gone, fire again — even past the configured hour."""
    from core.loops import process_nightly_memory

    config = _setup(tmp_path, dreamer_hour=4)
    state = vm.State()
    state.persisted.last_dreamer_run = dt.datetime(2025, 6, 14, 4, 0, 0)  # yesterday
    later_today = dt.datetime(2025, 6, 15, 7, 30, 0)

    with (
        patch("core.loops._now", return_value=later_today),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert len(list(config.notifications_dir.glob("nightly_dream-*.json"))) == 1


def test_catches_up_past_midnight_for_late_dreamer_hour(tmp_path):
    """A late dreamer_hour (e.g. 22:00) must still catch up after midnight.

    Protects against a regression where the window `hour < dreamer_hour + CATCHUP` had no
    modulo-24 wraparound, so post-midnight hours (0-3) silently fell through and the dream
    was dropped for the day.
    """
    from core.loops import process_nightly_memory

    config = _setup(tmp_path, dreamer_hour=22)
    state = vm.State()
    state.persisted.last_dreamer_run = dt.datetime(2025, 6, 14, 22, 0, 0)  # prior day
    after_midnight = dt.datetime(2025, 6, 15, 1, 0, 0)  # within 22:00 + 6h window

    with (
        patch("core.loops._now", return_value=after_midnight),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert len(list(config.notifications_dir.glob("nightly_dream-*.json"))) == 1


def test_skips_outside_catchup_window_for_late_dreamer_hour(tmp_path):
    """With dreamer_hour=22, an afternoon hour (14:00) is outside the circular window and must not fire."""
    from core.loops import process_nightly_memory

    config = _setup(tmp_path, dreamer_hour=22)
    state = vm.State()
    afternoon = dt.datetime(2025, 6, 15, 14, 0, 0)

    with (
        patch("core.loops._now", return_value=afternoon),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert list(config.notifications_dir.glob("nightly_dream-*.json")) == []


def test_drop_does_not_persist_last_dreamer_run(tmp_path):
    """Dropping the notification must not advance persisted.last_dreamer_run — only the agent's mark_dreamer_complete call does that.

    Protects against a regression where last_dreamer_run was committed at drop time, which locked the
    dreamer out for the day even if it never actually ran.
    """
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    state = vm.State()
    fake_now = dt.datetime(2025, 6, 15, config.nightly_memory_hour, 0, 0)

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert state.persisted.last_dreamer_run is None


# --- mark_dreamer_complete: keep the session, then compact + restart (not a hard reset) ---


def _mark_dreamer_complete_handler(state, config):
    from core.tools import build_vesta_tools_server

    server = build_vesta_tools_server(state, config)
    return next(t.handler for t in server.tools if t.name == "mark_dreamer_complete")


@pytest.mark.anyio
async def test_mark_dreamer_complete_keeps_session_and_defers_compact_restart(tmp_path):
    """The session is kept (so the restart resumes the compacted conversation) and the restart
    is deferred to the idle drain via compact_then_restart — not triggered inline mid-turn."""
    config = _setup(tmp_path)
    state = vm.State()
    state.persisted.session_id = "sess-abc"

    await _mark_dreamer_complete_handler(state, config)({})

    assert state.persisted.session_id == "sess-abc", "session must be kept for a resuming restart"
    assert state.compact_then_restart is True
    assert state.persisted.show_dreamer_summary is True
    assert state.persisted.last_dreamer_run is not None
    assert state.persisted.last_restart_reason == vm.NIGHTLY_RESTART
    # The restart happens after compaction in the drain, so the tool itself must NOT shut down.
    assert not state.graceful_shutdown.is_set()


# --- compact_then_restart_if_requested drain ---


@pytest.mark.anyio
async def test_drain_compacts_then_triggers_restart():
    from core.loops import compact_then_restart_if_requested

    state = vm.State()
    client = AsyncMock()
    state.client = tp.cast(ClaudeSDKClient, client)
    state.compact_then_restart = True

    await compact_then_restart_if_requested(state=state)

    client.compact.assert_awaited_once()
    assert state.compact_then_restart is False
    assert state.compacting is False
    assert state.graceful_shutdown.is_set()


@pytest.mark.anyio
async def test_drain_is_noop_when_not_requested():
    from core.loops import compact_then_restart_if_requested

    state = vm.State()
    client = AsyncMock()
    state.client = tp.cast(ClaudeSDKClient, client)

    await compact_then_restart_if_requested(state=state)

    client.compact.assert_not_awaited()
    assert not state.graceful_shutdown.is_set()


@pytest.mark.anyio
async def test_drain_restarts_even_when_compaction_fails():
    """A failed compaction must not strand the agent: it logs and restarts anyway (resume still
    works on the un-compacted session)."""
    from core.loops import compact_then_restart_if_requested

    state = vm.State()
    client = AsyncMock()
    client.compact.side_effect = ClaudeSDKError("boom")
    state.client = tp.cast(ClaudeSDKClient, client)
    state.compact_then_restart = True

    await compact_then_restart_if_requested(state=state)

    assert state.compacting is False
    assert state.graceful_shutdown.is_set()


@pytest.mark.anyio
async def test_notification_file_deleted_before_processing_is_lost_on_restart(tmp_path):
    """BUG: A notification arriving while compaction runs is silently lost on restart.

    process_batch deletes the file immediately after queue.put (loops.py line 124).
    compact_then_restart_if_requested then calls client.compact() and sets graceful_shutdown.
    run_vesta cancels all tasks and the in-memory asyncio.Queue is dropped with the process.
    A restarted process finds an empty notifications dir and the message is gone with no trace.
    """
    from core.loops import process_batch, compact_then_restart_if_requested, load_notifications

    config = _setup(tmp_path)
    state = vm.State()

    # Simulate a user notification arriving while the dreamer's compaction is running.
    notif_file = config.notifications_dir / "user-msg.json"
    notif = vm.Notification(
        timestamp=dt.datetime(2025, 1, 1),
        source="telegram",
        type="message",
        interrupt=True,
        body="urgent user message",
    )
    notif_file.write_text(notif.model_dump_json())
    notif.file_path = str(notif_file)

    dying_queue: asyncio.Queue[tuple[str, bool, list[str]]] = asyncio.Queue()

    # monitor_loop calls process_batch on the interrupt notification.
    # process_batch queues the message and keeps the file on disk until processing completes.
    with patch("core.loops.load_prompt", return_value=""), patch("core.loops.attempt_interrupt", new_callable=AsyncMock):
        await process_batch([notif], queue=dying_queue, state=state, config=config)

    # File is preserved on disk until after the message is fully processed (the fix).
    assert notif_file.exists(), "process_batch must not delete the file before processing completes"
    # Message sits in the queue waiting to be processed.
    assert dying_queue.qsize() == 1, "message is in the queue"

    # Compaction finishes: compact_then_restart_if_requested sets graceful_shutdown.
    state.compact_then_restart = True
    client = AsyncMock()
    state.client = tp.cast(ClaudeSDKClient, client)
    await compact_then_restart_if_requested(state=state)
    assert state.graceful_shutdown.is_set(), "graceful_shutdown fires after compaction"

    # The process restarts: run_vesta creates a fresh queue and init_state loads from disk.
    # A restarted process can only recover messages that are still on disk.
    recovered = await load_notifications(config=config)

    # The file was kept on disk by process_batch, so the restarted process recovers it.
    # The dying_queue (qsize=1) is dropped on restart, but the file provides durability.
    assert len(recovered) == 1, (
        f"Message queued mid-compact must survive restart (recovered {len(recovered)})."
        f" dying_queue qsize={dying_queue.qsize()} is dropped on restart."
    )
