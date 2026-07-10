"""Tests for the persistent state store."""

import concurrent.futures
import datetime as dt

import pytest

import core.config as cfg
import core.models as vm
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


def test_corrupt_state_with_no_events_db_starts_truly_fresh(tmp_path):
    """A corrupt state.json on a brand-new agent (no events.db yet) has nothing to corroborate
    against, so it falls back to first_start_done=False like today."""
    config = _config(tmp_path)
    state_store.state_path(config).write_text("not valid json {{{")

    state = state_store.load_state(config)

    assert state.first_start_done is False


def test_corrupt_state_with_existing_events_db_stays_a_veteran(tmp_path):
    """A corrupt state.json on a veteran agent (events.db already exists) must not re-onboard or
    silently pre-mark pending migrations on top of months of memory: it comes back as
    first_start_done=True so migrations re-run idempotently instead of being skipped."""
    from core.migrations import pending_migration_turns

    config = _config(tmp_path)
    (config.data_dir / "events.db").write_text("pretend this is a real sqlite file")
    state_store.state_path(config).write_text("not valid json {{{")

    state = state_store.load_state(config)
    assert state.first_start_done is True

    migrations_dir = config.agent_dir / "core" / "migrations"
    migrations_dir.mkdir(parents=True)
    (migrations_dir / "001-first.md").write_text("do the thing")

    turns = pending_migration_turns(state=vm.State(persisted=state), config=config, first_start=not state.first_start_done)

    assert len(turns) == 1, "the migration must queue as a real turn, not be pre-marked applied"
    assert state.applied_migrations == [], "pre-marking never happens on the veteran recovery path"
