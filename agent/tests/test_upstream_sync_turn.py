"""Upgrade-driven upstream sync: Git ancestry + boot turn."""

import asyncio
import subprocess

import core.config as cfg
import core.models as vm
from core import state_store
from core.tools import _vesta_tools
from core.upstream_sync import upstream_sync_turn, vesta_version, workspace_synced


def _config(tmp_path, version: str | None = "0.1.170") -> cfg.VestaConfig:
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    (config.agent_dir / "core").mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if version is not None:
        (config.agent_dir / "core" / "pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    return config


def _record_snapshot(config: cfg.VestaConfig, version: str) -> None:
    home = config.agent_dir.parent
    subprocess.run(["git", "init", "-q", "-b", "agent"], cwd=home, check=True)
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@vesta", "commit", "-q", "--allow-empty", "-m", "stock"],
        cwd=home,
        check=True,
    )
    subprocess.run(["git", "tag", f"agent-v{version}"], cwd=home, check=True)


def test_vesta_version_reads_core_pyproject(tmp_path):
    assert vesta_version(_config(tmp_path, "0.1.170")) == "0.1.170"


def test_vesta_version_unknown_when_missing_or_broken(tmp_path):
    assert vesta_version(_config(tmp_path, version=None)) == "unknown"
    config = _config(tmp_path, version=None)
    (config.agent_dir / "core" / "pyproject.toml").write_text("not toml [")
    assert vesta_version(config) == "unknown"


def test_turn_fires_on_version_mismatch_and_names_the_snapshot(tmp_path):
    config = _config(tmp_path, "0.1.171")
    turn = upstream_sync_turn(config=config, first_start=False)
    assert turn is not None
    assert "agent-v0.1.171" in turn
    assert "git merge --no-ff --no-edit agent-v0.1.171" in turn
    assert "upstream-sync/SKILL.md" in turn


def test_turn_fires_when_workspace_is_not_attached(tmp_path):
    assert upstream_sync_turn(config=_config(tmp_path), first_start=False) is not None


def test_legacy_synced_marker_is_ignored_in_favor_of_git(tmp_path):
    config = _config(tmp_path)
    (config.data_dir / "state.json").write_text('{"first_start_done":true,"last_synced_version":"0.1.170"}')
    persisted = state_store.load_state(config)
    assert not hasattr(persisted, "last_synced_version")
    assert upstream_sync_turn(config=config, first_start=False) is not None


def test_no_turn_when_snapshot_is_in_git_history(tmp_path):
    config = _config(tmp_path, "0.1.170")
    _record_snapshot(config, "0.1.170")
    assert workspace_synced(config, "0.1.170")
    assert upstream_sync_turn(config=config, first_start=False) is None


def test_no_turn_when_version_unknown_and_nothing_marked(tmp_path):
    assert upstream_sync_turn(config=_config(tmp_path, version=None), first_start=False) is None


def test_first_start_leaves_initial_attach_to_birth(tmp_path):
    config = _config(tmp_path, "0.1.170")
    assert upstream_sync_turn(config=config, first_start=True) is None
    assert not workspace_synced(config, "0.1.170")


def test_first_start_with_unknown_version_marks_nothing(tmp_path):
    assert upstream_sync_turn(config=_config(tmp_path, version=None), first_start=True) is None


def test_legacy_mark_upstream_synced_verifies_git_history(tmp_path):
    config = _config(tmp_path, "0.1.171")
    _record_snapshot(config, "0.1.171")
    state = vm.State()
    tools = {t.name: t for t in _vesta_tools(state, config)}
    result = asyncio.run(tools["mark_upstream_synced"].handler({}))
    assert "agent-v0.1.171" in result["content"][0]["text"]
    assert not result.get("isError", False)


def test_legacy_mark_upstream_synced_refuses_an_unmerged_snapshot(tmp_path):
    config = _config(tmp_path, "0.1.171")
    state = vm.State()
    tools = {t.name: t for t in _vesta_tools(state, config)}
    result = asyncio.run(tools["mark_upstream_synced"].handler({}))
    assert result["isError"] is True


def test_mark_workspace_synced_legacy_alias_still_verifies(tmp_path):
    """LEGACY(remove-when: no agent predating the rename release remains): released
    migration prompts call the old tool name verbatim."""
    config = _config(tmp_path, "0.1.171")
    _record_snapshot(config, "0.1.171")
    state = vm.State()
    tools = {t.name: t for t in _vesta_tools(state, config)}
    result = asyncio.run(tools["mark_workspace_synced"].handler({}))
    assert "0.1.171" in result["content"][0]["text"]
