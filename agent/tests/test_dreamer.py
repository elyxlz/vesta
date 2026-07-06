"""Tests for nightly dreamer/memory scheduling."""

import asyncio
import datetime as dt
import json
import typing as tp
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.models as vm
from conftest import consuming
from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError, ResultMessage, SystemMessage
from wait_util import wait_for_condition


def _setup(tmp_path, *, dreamer_hour=4):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", nightly_memory_hour=dreamer_hour)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_skips_dream_before_first_start_done(tmp_path):
    """A brand-new agent (first_start_done=False) has nothing to curate, so a catch-up dream
    landing inside the morning window must not fire mid-onboarding."""
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    state = vm.State()
    assert state.persisted.first_start_done is False
    fake_now = dt.datetime(2025, 6, 15, config.nightly_memory_hour, 0, 0)

    # No load_prompt patch: the first_start_done guard returns before load_prompt is reached.
    with patch("core.loops._now", return_value=fake_now):
        process_nightly_memory(state=state, config=config)

    assert list(config.notifications_dir.glob("nightly_dream-*.json")) == []


def test_drops_dream_notification(tmp_path):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path)
    state = vm.State()
    state.persisted.first_start_done = True
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


@pytest.mark.parametrize(
    "dreamer_hour,last_dreamer_run,now,expected_files",
    [
        (4, dt.datetime(2025, 6, 15, 4, 0, 0), dt.datetime(2025, 6, 15, 4, 0, 0), 0),  # already ran today
        (4, None, dt.datetime(2025, 6, 15, 2, 0, 0), 0),  # before the dreamer hour
        (4, dt.datetime(2025, 6, 14, 4, 0, 0), dt.datetime(2025, 6, 15, 7, 30, 0), 1),  # not done today, retry past the hour
        # Late dreamer_hour (22:00) must catch up after midnight: the window is circular (modulo-24), so
        # post-midnight hours (0-3) must not fall through and drop the dream for the day.
        (22, dt.datetime(2025, 6, 14, 22, 0, 0), dt.datetime(2025, 6, 15, 1, 0, 0), 1),  # within 22:00 + 6h window
        (22, None, dt.datetime(2025, 6, 15, 14, 0, 0), 0),  # afternoon is outside the circular window
    ],
    ids=["already-ran-today", "before-hour", "retry-past-hour", "catchup-past-midnight", "outside-window"],
)
def test_nightly_memory_scheduling(tmp_path, dreamer_hour, last_dreamer_run, now, expected_files):
    from core.loops import process_nightly_memory

    config = _setup(tmp_path, dreamer_hour=dreamer_hour)
    state = vm.State()
    state.persisted.first_start_done = True
    state.persisted.last_dreamer_run = last_dreamer_run

    with (
        patch("core.loops._now", return_value=now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        process_nightly_memory(state=state, config=config)

    assert len(list(config.notifications_dir.glob("nightly_dream-*.json"))) == expected_files


# --- mark_dreamer_complete: keep the session, then compact + restart (not a hard reset) ---


def _mark_dreamer_complete_handler(state, config):
    from core.tools import _vesta_tools

    tools = _vesta_tools(state, config)
    return next(t.handler for t in tools if t.name == "mark_dreamer_complete")


@pytest.mark.anyio
async def test_mark_dreamer_complete_stamps_timestamp_only(tmp_path):
    """Pure recorder: stamps last_dreamer_run; touches no summary, restart, or compaction state.
    The compaction/restart is composed separately via compact_context."""
    config = _setup(tmp_path)
    state = vm.State()
    state.persisted.session_id = "sess-abc"

    await _mark_dreamer_complete_handler(state, config)({})

    assert state.persisted.last_dreamer_run is not None
    assert state.persisted.session_id == "sess-abc"
    assert state.pending_compaction is None
    assert not state.graceful_shutdown.is_set()


# --- compact_context: the compaction primitive ---


def _tool_handler(state, config, name):
    from core.tools import _vesta_tools

    return next(t.handler for t in _vesta_tools(state, config) if t.name == name)


@pytest.mark.anyio
async def test_compact_context_sets_nap_descriptor(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()

    await _tool_handler(state, config, "compact_context")({"instructions": "keep threads", "followup": "reflect briefly"})

    assert state.pending_compaction == vm.PendingCompaction(instructions="keep threads", followup="reflect briefly", restart=False)


@pytest.mark.anyio
async def test_compact_context_defaults_followup_none_and_restart_false(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()

    await _tool_handler(state, config, "compact_context")({"instructions": "keep threads"})

    assert state.pending_compaction == vm.PendingCompaction(instructions="keep threads", followup=None, restart=False)


@pytest.mark.anyio
async def test_compact_context_rejects_empty_instructions(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()

    result = await _tool_handler(state, config, "compact_context")({"instructions": "   "})

    assert state.pending_compaction is None
    assert "error" in result["content"][0]["text"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "restart_arg,expected",
    [(True, True), ("true", True), ("TRUE", True), (False, False), ("false", False), ("", False)],
    ids=["bool-true", "str-true", "str-true-caps", "bool-false", "str-false", "str-empty"],
)
async def test_compact_context_restart_only_true_on_real_true(tmp_path, restart_arg, expected):
    config = _setup(tmp_path)
    state = vm.State()

    await _tool_handler(state, config, "compact_context")({"instructions": "keep", "restart": restart_arg})

    assert state.pending_compaction.restart is expected


# --- drain_compaction_request: compact, then route the follow-up ---


async def _run_with_compaction_stream(state, config, action, *, pre_tokens):
    """Run `action` with the real stream consumer fed a compaction turn (boundary then result).

    The stream waits for compact_session to open its turn (the real CLI only responds after the
    /compact query), then yields the boundary and the turn-closing ResultMessage."""
    state.persisted.session_id = state.persisted.session_id or "sess-compact"
    client = AsyncMock()

    async def stream():
        await wait_for_condition(lambda: state.turn is not None, message="compact_session never opened a turn")
        yield SystemMessage(subtype="compact_boundary", data={"compact_metadata": {"pre_tokens": pre_tokens, "trigger": "manual"}})
        yield ResultMessage(
            subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id=state.persisted.session_id
        )
        await asyncio.Event().wait()

    client.receive_messages = MagicMock(side_effect=lambda: stream())
    state.client = tp.cast(ClaudeSDKClient, client)
    async with consuming(state, config):
        await asyncio.wait_for(action(), timeout=5.0)
    return client


def _mock_compact_client():
    # These drain tests stub compact_session itself to isolate follow-up routing from the SDK stream.
    return tp.cast(ClaudeSDKClient, AsyncMock())


@pytest.mark.anyio
async def test_drain_nap_drops_oriented_followup_notification(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()
    state.client = _mock_compact_client()
    state.pending_compaction = vm.PendingCompaction(instructions="keep", followup="tell the user", restart=False)

    with (
        patch("core.loops.compact_session", new_callable=AsyncMock),
        patch("core.loops.vestad_client.request_restart", new_callable=AsyncMock, return_value=True) as restart,
    ):
        from core.loops import drain_compaction_request

        await drain_compaction_request(state=state, config=config)

    restart.assert_not_awaited()
    assert state.pending_compaction is None
    assert state.persisted.pending_boot_message is None
    files = list(config.notifications_dir.glob(f"{vm.TYPE_COMPACTION_FOLLOWUP}-*.json"))
    assert len(files) == 1
    body = json.loads(files[0].read_text())["body"]
    assert body.startswith("[Your context was just compacted; the summary is above.]")
    assert "tell the user" in body


@pytest.mark.anyio
async def test_drain_nap_without_followup_drops_nothing(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()
    state.client = _mock_compact_client()
    state.pending_compaction = vm.PendingCompaction(instructions="keep", followup=None, restart=False)

    with patch("core.loops.compact_session", new_callable=AsyncMock):
        from core.loops import drain_compaction_request

        await drain_compaction_request(state=state, config=config)

    assert list(config.notifications_dir.glob(f"{vm.TYPE_COMPACTION_FOLLOWUP}-*.json")) == []


@pytest.mark.anyio
async def test_drain_nap_dedups_followup_when_one_pending(tmp_path):
    config = _setup(tmp_path)
    (config.notifications_dir / f"{vm.TYPE_COMPACTION_FOLLOWUP}-1.json").write_text("{}")
    state = vm.State()
    state.client = _mock_compact_client()
    state.pending_compaction = vm.PendingCompaction(instructions="keep", followup="reflect", restart=False)

    with patch("core.loops.compact_session", new_callable=AsyncMock):
        from core.loops import drain_compaction_request

        await drain_compaction_request(state=state, config=config)

    assert len(list(config.notifications_dir.glob(f"{vm.TYPE_COMPACTION_FOLLOWUP}-*.json"))) == 1


@pytest.mark.anyio
async def test_drain_restart_boot_message_and_no_notification(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()
    state.client = _mock_compact_client()
    state.pending_compaction = vm.PendingCompaction(instructions="keep", followup="new day, greet warmly", restart=True)

    with (
        patch("core.loops.compact_session", new_callable=AsyncMock),
        patch("core.loops.vestad_client.request_restart", new_callable=AsyncMock, return_value=True) as restart,
    ):
        from core.loops import drain_compaction_request

        await drain_compaction_request(state=state, config=config)

    restart.assert_awaited_once()
    assert state.persisted.pending_boot_message.startswith("[Your context was just compacted; the summary is above.]")
    assert "new day, greet warmly" in state.persisted.pending_boot_message
    assert list(config.notifications_dir.glob(f"{vm.TYPE_COMPACTION_FOLLOWUP}-*.json")) == []


@pytest.mark.anyio
async def test_drain_restart_unreachable_clears_boot_message(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()
    state.client = _mock_compact_client()
    state.pending_compaction = vm.PendingCompaction(instructions="keep", followup="new day", restart=True)

    with (
        patch("core.loops.compact_session", new_callable=AsyncMock),
        patch("core.loops.vestad_client.request_restart", new_callable=AsyncMock, return_value=False),
    ):
        from core.loops import drain_compaction_request

        await drain_compaction_request(state=state, config=config)

    assert state.persisted.pending_boot_message is None


@pytest.mark.anyio
async def test_drain_compaction_failure_is_nonfatal(tmp_path):
    config = _setup(tmp_path)
    state = vm.State()
    state.client = _mock_compact_client()
    state.pending_compaction = vm.PendingCompaction(instructions="keep", followup="reflect", restart=False)

    with patch("core.loops.compact_session", new_callable=AsyncMock, side_effect=ClaudeSDKError("boom")):
        from core.loops import drain_compaction_request

        await drain_compaction_request(state=state, config=config)

    # Core stays dumb about compaction success: the follow-up is still delivered.
    assert len(list(config.notifications_dir.glob(f"{vm.TYPE_COMPACTION_FOLLOWUP}-*.json"))) == 1
    assert state.compacting is False


@pytest.mark.anyio
async def test_notification_file_deleted_before_processing_is_lost_on_restart(tmp_path):
    """BUG: A notification arriving while compaction runs is silently lost on restart.

    process_batch deletes the file immediately after queue.put (loops.py line 124).
    drain_compaction_request then compacts the session and requests the restart.
    run_vesta cancels all tasks and the in-memory asyncio.Queue is dropped with the process.
    A restarted process finds an empty notifications dir and the message is gone with no trace.
    """
    from core.loops import process_batch, drain_compaction_request, load_notifications

    config = _setup(tmp_path)
    state = vm.State()

    # Simulate a user notification arriving while the dreamer's compaction is running.
    notif_file = config.notifications_dir / "user-msg.json"
    notif = vm.Notification(
        timestamp=dt.datetime(2025, 1, 1),
        source="telegram",
        type="message",
        body="urgent user message",
    )
    notif_file.write_text(notif.model_dump_json())
    notif.file_path = str(notif_file)

    dying_queue: asyncio.Queue[vm.QueuedTurn] = asyncio.Queue()

    # monitor_loop calls process_batch on the interrupt notification.
    # process_batch queues the message and keeps the file on disk until processing completes.
    with patch("core.loops.load_prompt", return_value=""), patch("core.loops.attempt_interrupt", new_callable=AsyncMock):
        await process_batch([notif], queue=dying_queue, state=state, config=config)

    # File is preserved on disk until after the message is fully processed (the fix).
    assert notif_file.exists(), "process_batch must not delete the file before processing completes"
    # Message sits in the queue waiting to be processed.
    assert dying_queue.qsize() == 1, "message is in the queue"

    # Compaction finishes: the drain compacts, then requests the restart (via vestad).
    state.pending_compaction = vm.PendingCompaction(instructions=None, followup="new day", restart=True)
    with patch("core.loops.vestad_client.request_restart", new_callable=AsyncMock, return_value=True) as restart:
        await _run_with_compaction_stream(state, config, lambda: drain_compaction_request(state=state, config=config), pre_tokens=1)
    restart.assert_awaited_once()  # restart fires after compaction (via vestad)

    # The process restarts: run_vesta creates a fresh queue and init_state loads from disk.
    # A restarted process can only recover messages that are still on disk.
    recovered = await load_notifications(config=config)

    # The file was kept on disk by process_batch, so the restarted process recovers it.
    # The dying_queue (qsize=1) is dropped on restart, but the file provides durability.
    assert len(recovered) == 1, (
        f"Message queued mid-compact must survive restart (recovered {len(recovered)})."
        f" dying_queue qsize={dying_queue.qsize()} is dropped on restart."
    )
