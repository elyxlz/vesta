"""Upgrade-driven upstream sync: version marker + boot turn (spec Part 1)."""

import asyncio

import core.models as vm
from core import state_store
from core.tools import _vesta_tools
from core.upgrade_sync import upgrade_sync_turn, vesta_version


def _config(tmp_path, version: str | None = "0.1.170") -> vm.VestaConfig:
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    (config.agent_dir / "core").mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if version is not None:
        (config.agent_dir / "core" / "pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    return config


def test_vesta_version_reads_core_pyproject(tmp_path):
    assert vesta_version(_config(tmp_path, "0.1.170")) == "0.1.170"


def test_vesta_version_unknown_when_missing_or_broken(tmp_path):
    assert vesta_version(_config(tmp_path, version=None)) == "unknown"
    config = _config(tmp_path, version=None)
    (config.agent_dir / "core" / "pyproject.toml").write_text("not toml [")
    assert vesta_version(config) == "unknown"


def test_turn_fires_on_version_mismatch_and_names_the_snapshot(tmp_path):
    config = _config(tmp_path, "0.1.171")
    state = vm.State()
    state.persisted.last_synced_version = "0.1.170"
    turn = upgrade_sync_turn(state=state, config=config, first_start=False)
    assert turn is not None
    assert "agent-v0.1.171" in turn
    assert "mark_upstream_synced" in turn


def test_turn_fires_when_marker_absent_legacy_agent(tmp_path):
    state = vm.State()
    assert state.persisted.last_synced_version is None
    assert upgrade_sync_turn(state=state, config=_config(tmp_path), first_start=False) is not None


def test_no_turn_when_versions_match(tmp_path):
    state = vm.State()
    state.persisted.last_synced_version = "0.1.170"
    assert upgrade_sync_turn(state=state, config=_config(tmp_path, "0.1.170"), first_start=False) is None


def test_no_turn_when_version_unknown_and_nothing_marked(tmp_path):
    state = vm.State()
    assert upgrade_sync_turn(state=state, config=_config(tmp_path, version=None), first_start=False) is None
    assert state.persisted.last_synced_version is None


def test_first_start_pre_marks_and_returns_none(tmp_path):
    config = _config(tmp_path, "0.1.170")
    state = vm.State()
    assert upgrade_sync_turn(state=state, config=config, first_start=True) is None
    assert state.persisted.last_synced_version == "0.1.170"
    assert state_store.load_state(config).last_synced_version == "0.1.170"


def test_first_start_with_unknown_version_marks_nothing(tmp_path):
    state = vm.State()
    assert upgrade_sync_turn(state=state, config=_config(tmp_path, version=None), first_start=True) is None
    assert state.persisted.last_synced_version is None


def test_mark_upstream_synced_records_running_version(tmp_path):
    config = _config(tmp_path, "0.1.171")
    state = vm.State()
    state.persisted.last_synced_version = "0.1.170"
    tools = {t.name: t for t in _vesta_tools(state, config)}
    result = asyncio.run(tools["mark_upstream_synced"].handler({}))
    assert "0.1.171" in result["content"][0]["text"]
    assert state.persisted.last_synced_version == "0.1.171"
    assert state_store.load_state(config).last_synced_version == "0.1.171"
