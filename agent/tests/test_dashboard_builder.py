"""Core registers the dashboard-builder subagent on the SDK options; these tests cover that."""

import pathlib as pl

import core.config as cfg
from core.client import build_client_options

SHIPPED_PROMPT = pl.Path(__file__).resolve().parents[1] / "core" / "prompts" / "dashboard_builder.md"


def _config(tmp_path, monkeypatch):
    # AGENT_DIR drives both the config field and config_store_path(); the provider makes it signed in.
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    cfg.update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    config = cfg.VestaConfig()
    config.core_prompts_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("my memory body")
    return config


def _install_skill(config):
    (config.skills_dir / "dashboard").mkdir(parents=True, exist_ok=True)


def _ship_prompt(config):
    (config.core_prompts_dir / "dashboard_builder.md").write_text("builder expertise")


def test_dashboard_builder_is_registered_with_its_prompt_and_the_dashboard_skill(tmp_path, state, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    _install_skill(config)
    _ship_prompt(config)
    agents = build_client_options(config, state).agents
    assert agents is not None
    builder = agents["dashboard-builder"]
    assert builder.prompt == "builder expertise"
    assert builder.skills == ["dashboard"]
    # Unset so the builder inherits the user's provider model; a hardcoded "opus" would override it
    # and does not resolve on OpenRouter.
    assert builder.model is None
    assert builder.effort is None


def test_no_builder_is_registered_when_the_dashboard_skill_is_not_installed(tmp_path, state, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    _ship_prompt(config)
    assert build_client_options(config, state).agents == {}


def test_no_builder_is_registered_when_the_prompt_is_missing(tmp_path, state, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    _install_skill(config)
    assert build_client_options(config, state).agents == {}


def test_the_builder_prompt_ships_in_core_prompts():
    # Registration no-ops silently without it, so the shipped file is the contract.
    assert SHIPPED_PROMPT.read_text().strip()
