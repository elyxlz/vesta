"""Tests for the persistent state store."""

import concurrent.futures
import datetime as dt

import pytest

import core.config as cfg
from core.state_store import PersistedState
from core import state_store


def _config(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_load_returns_defaults_when_no_state(tmp_path):
    config = _config(tmp_path)
    state = state_store.load_state(config)
    assert state == PersistedState()
    # First load creates the file.
    assert state_store.state_path(config).exists()


def test_save_then_load_round_trip(tmp_path):
    config = _config(tmp_path)
    original = PersistedState(
        first_start_done=True,
        last_restart_reason="clean",
        last_dreamer_run=dt.datetime(2026, 1, 2, 3, 4, 5),
        pending_boot_message="[Your context was just compacted; the summary is above.]\n\nnew day",
        session_id="abc-123",
        applied_migrations=["mig-1", "mig-2"],
    )
    state_store.save_state(original, config)
    reloaded = state_store.load_state(config)
    assert reloaded == original


def test_save_is_atomic(tmp_path):
    """tmp + rename: a partial write must never leave the canonical state.json corrupt."""
    config = _config(tmp_path)
    state_store.save_state(PersistedState(session_id="first"), config)
    # Pre-create a stale tmp from a hypothetical crashed write: it is ignored, never read back as state.
    tmp = state_store.state_path(config).with_suffix(".json.tmp")
    tmp.write_text("garbage")
    state_store.save_state(PersistedState(session_id="second"), config)
    assert state_store.load_state(config).session_id == "second"


def test_concurrent_saves_never_corrupt(tmp_path):
    """save_state_async dispatches writes to worker threads, so saves can overlap; each write must
    land whole (unique tmp + atomic rename), with one full writer winning, never a torn file."""
    config = _config(tmp_path)
    session_ids = [f"session-{i}" for i in range(32)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda sid: state_store.save_state(PersistedState(session_id=sid), config), session_ids))
    assert state_store.load_state(config).session_id in session_ids


@pytest.mark.anyio
async def test_save_state_async_round_trip(tmp_path):
    config = _config(tmp_path)
    await state_store.save_state_async(PersistedState(session_id="saved-off-loop"), config)
    assert state_store.load_state(config).session_id == "saved-off-loop"
