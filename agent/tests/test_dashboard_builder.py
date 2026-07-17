"""The dashboard skill designs the change, writes a spec, and dispatches the dashboard-builder
subagent to build it, so the token-heavy build churn stays out of the main conversation. Core
registers that named agent on the SDK options; these tests cover the registration."""

import pathlib as pl

import core.config as cfg
from core.client import build_client_options

REPO_ROOT = pl.Path(__file__).resolve().parents[2]


def _config(tmp_path, monkeypatch):
    # Drive agent_dir through AGENT_DIR so the config field and config_store_path() agree.
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    # A signed-in agent: build_client_options needs a chosen provider.
    from core.config import update_config_store

    update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    config = cfg.VestaConfig()
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("my memory body")
    return config


def _install_dashboard_skill(config):
    (config.skills_dir / "dashboard").mkdir(parents=True, exist_ok=True)


def _ship_builder_prompt(config, body: str):
    config.core_prompts_dir.mkdir(parents=True, exist_ok=True)
    (config.core_prompts_dir / "dashboard_builder.md").write_text(body)


def test_dashboard_builder_is_registered_with_its_prompt_and_the_dashboard_skill(tmp_path, state, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    _install_dashboard_skill(config)
    _ship_builder_prompt(config, "builder expertise")
    agents = build_client_options(config, state).agents
    assert agents is not None
    builder = agents["dashboard-builder"]
    assert builder.prompt == "builder expertise"
    assert builder.skills == ["dashboard"]
    # Model and effort are left to the session, so the builder runs on the user's chosen provider
    # model; hardcoding one would override that choice and break non-Anthropic providers.
    assert builder.model is None
    assert builder.effort is None


def test_no_builder_is_registered_when_the_dashboard_skill_is_not_installed(tmp_path, state, monkeypatch):
    # The sparse cone leaves an uninstalled skill off disk: advertise no builder rather than one
    # that preloads a skill the box does not have.
    config = _config(tmp_path, monkeypatch)
    _ship_builder_prompt(config, "builder expertise")
    assert build_client_options(config, state).agents == {}


def test_no_builder_is_registered_when_the_prompt_is_missing(tmp_path, state, monkeypatch):
    config = _config(tmp_path, monkeypatch)
    _install_dashboard_skill(config)
    assert build_client_options(config, state).agents == {}


def test_the_builder_prompt_ships_in_core_prompts():
    # Registration no-ops silently without it, so the shipped file is the contract.
    assert (REPO_ROOT / "agent" / "core" / "prompts" / "dashboard_builder.md").read_text().strip()
