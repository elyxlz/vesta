"""Tests for the persistent state store."""

import datetime as dt

import core.models as vm
from core import state_store


def _config(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_load_returns_defaults_when_no_state_or_legacy(tmp_path):
    config = _config(tmp_path)
    state = state_store.load_state(config)
    assert state == vm.PersistedState()
    # First load creates the file.
    assert state_store.state_path(config).exists()


def test_save_then_load_round_trip(tmp_path):
    config = _config(tmp_path)
    original = vm.PersistedState(
        first_start_done=True,
        last_restart_reason="clean",
        last_dreamer_run=dt.datetime(2026, 1, 2, 3, 4, 5),
        show_dreamer_summary=True,
        session_id="abc-123",
        applied_migrations=["mig-1", "mig-2"],
    )
    state_store.save_state(original, config)
    reloaded = state_store.load_state(config)
    assert reloaded == original


def test_legacy_files_are_imported_and_removed(tmp_path):
    config = _config(tmp_path)
    d = config.data_dir
    (d / "first_start_done").write_text("1")
    (d / "restart_reason").write_text("clean restart\n")
    (d / "last_dreamer_run").write_text("2026-01-02T03:04:05\n")
    (d / "show_dreamer_summary").write_text("1")
    (d / "session_id").write_text("legacy-session-id-1234567890\n")
    (d / "migrations.applied").write_text("mig-1\nmig-2\n\n")

    state = state_store.load_state(config)

    assert state.first_start_done is True
    assert state.last_restart_reason == "clean restart"
    assert state.last_dreamer_run == dt.datetime(2026, 1, 2, 3, 4, 5)
    assert state.show_dreamer_summary is True
    assert state.session_id == "legacy-session-id-1234567890"
    assert state.applied_migrations == ["mig-1", "mig-2"]

    for name in state_store.LEGACY_FILES:
        assert not (d / name).exists(), f"legacy file {name} should be removed"


def test_save_is_atomic(tmp_path):
    """tmp + rename: a partial write must never leave the canonical state.json corrupt."""
    config = _config(tmp_path)
    state_store.save_state(vm.PersistedState(session_id="first"), config)
    # Pre-create a stale tmp from a hypothetical crashed write — save_state must overwrite it.
    tmp = state_store.state_path(config).with_suffix(".json.tmp")
    tmp.write_text("garbage")
    state_store.save_state(vm.PersistedState(session_id="second"), config)
    assert state_store.load_state(config).session_id == "second"


def test_load_with_existing_state_ignores_legacy_files(tmp_path):
    """If state.json already exists, legacy markers are leftover noise — don't merge them."""
    config = _config(tmp_path)
    state_store.save_state(vm.PersistedState(session_id="from-state-json"), config)
    (config.data_dir / "session_id").write_text("legacy-noise")

    state = state_store.load_state(config)
    assert state.session_id == "from-state-json"
    # Legacy file is left alone (only removed during the import path, not on every load).
    assert (config.data_dir / "session_id").exists()
