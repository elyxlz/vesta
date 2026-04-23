"""Tests for nightly dreamer/memory scheduling."""

import asyncio
import datetime as dt
from unittest.mock import patch

import pytest
import core.models as vm
from test_processor import _run_processor_test


@pytest.mark.anyio
async def test_queues_prompt_and_archives(tmp_path):
    from core.loops import process_nightly_memory

    state = vm.State()
    state.last_dreamer_run = None
    queue: asyncio.Queue = asyncio.Queue()

    dreamer_hour = 4
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        await process_nightly_memory(queue, state=state, config=config)

    assert not queue.empty()
    msg, is_user = await queue.get()
    assert msg == "dreamer prompt"
    assert is_user is False
    assert state.last_dreamer_run == fake_now
    assert state.dreamer_active is True


@pytest.mark.anyio
async def test_skips_when_already_run_today(tmp_path):
    from core.loops import process_nightly_memory

    dreamer_hour = 4
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    state = vm.State()
    state.last_dreamer_run = fake_now
    queue: asyncio.Queue = asyncio.Queue()

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        await process_nightly_memory(queue, state=state, config=config)

    assert queue.empty()
    assert state.dreamer_active is False


@pytest.mark.anyio
async def test_clears_session_and_restarts(tmp_path):
    async def side_effect(msg, *, state, config, is_user):
        return (["OK"], state)

    pre_state = vm.State()
    pre_state.session_id = "pre-dreamer-session"
    pre_state.dreamer_active = True
    pre_state.last_dreamer_run = dt.datetime(2025, 6, 15, 4, 0, 0)

    fake_now = dt.datetime(2025, 6, 15, 4, 5, 0)
    state, session_count, messages = await _run_processor_test(
        tmp_path,
        message_side_effect=side_effect,
        pre_state=pre_state,
        initial_queue=[("dreamer prompt content", False)],
        extra_patches={"core.loops._now": lambda: fake_now},
    )
    # Session should be cleared (not preserved) so the next boot starts fresh
    assert state.session_id is None
    assert state.dreamer_active is False
    assert state.graceful_shutdown.is_set()
    assert state.restart_reason == "nightly — dreamer ran, session cleared for fresh context"
    # No /compact message — session deletion replaces it
    assert messages == ["dreamer prompt content"]
    # last_dreamer_run is persisted to disk only on completion
    persisted = (tmp_path / "agent" / "data" / "last_dreamer_run").read_text().strip()
    assert persisted == pre_state.last_dreamer_run.isoformat()


@pytest.mark.anyio
async def test_queue_does_not_persist_last_dreamer_run(tmp_path):
    """If the dreamer is queued but never completes (e.g. backup interrupts), disk must stay stale.

    Protects against a bug where last_dreamer_run was written at queue time, which locked the
    dreamer out for the day even if it never actually ran.
    """
    from core.loops import process_nightly_memory

    state = vm.State()
    state.last_dreamer_run = None
    queue: asyncio.Queue = asyncio.Queue()

    dreamer_hour = 4
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", nightly_memory_hour=dreamer_hour)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    with (
        patch("core.loops._now", return_value=fake_now),
        patch("core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        await process_nightly_memory(queue, state=state, config=config)

    assert state.last_dreamer_run == fake_now
    assert not (config.data_dir / "last_dreamer_run").exists()
