"""Upgrade-driven upstream sync: Git ancestry + boot turn."""

import asyncio
import os
import subprocess

from test_upstream_sync import BASE_ENV  # hermetic-git env, as build-upstream.sh uses

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
    """A box's checkout at `version`: history carrying the agent-v<version> tag. Runs under the same
    hermetic env build-upstream.sh exports, so the host's own git config cannot reach it (a user-level
    tag.gpgSign turns `git tag` into a signed annotated tag, which fails without a message)."""
    home = config.agent_dir.parent
    env = os.environ | BASE_ENV
    for args in (["init", "-q", "-b", "agent"], ["commit", "-q", "--allow-empty", "-m", "stock"], ["tag", f"agent-v{version}"]):
        subprocess.run(["git", *args], cwd=home, check=True, env=env)


def test_snapshot_fixtures_ignore_a_hostile_host_git_config(tmp_path, monkeypatch):
    """A developer with tag.gpgSign/commit.gpgSign set globally must still be able to run the suite:
    signing turns `git tag` into an annotated tag and fails for want of a message."""
    hostile = tmp_path / "hostile.gitconfig"
    hostile.write_text("[tag]\n\tgpgsign = true\n[commit]\n\tgpgsign = true\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hostile))

    config = _config(tmp_path)
    _record_snapshot(config, "0.1.170")

    assert workspace_synced(config, "0.1.170")


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
