"""Tests for VestaConfig and initialization."""

import asyncio
import os

from core.helpers import get_memory_path


def test_config_paths_under_agent_dir(config, tmp_path):
    assert config.notifications_dir.is_relative_to(config.agent_dir)
    assert config.data_dir.is_relative_to(config.agent_dir)
    assert config.logs_dir.is_relative_to(config.agent_dir)
    assert config.skills_dir.is_relative_to(config.agent_dir)


def test_config_default_values():
    import core.models as vm

    config = vm.VestaConfig()
    assert config.monitor_tick_interval > 0
    assert config.response_timeout > 0


def test_memory_paths(config):
    assert get_memory_path(config) == config.agent_dir / "MEMORY.md"
    assert config.skills_dir == config.agent_dir / "skills"


def test_thinking_legacy_json_dict_coerces_with_defaults(monkeypatch):
    """Env files written before adaptive.display was required carry the JSON-dict form
    (e.g. THINKING='{"type":"adaptive"}'); it must coerce, not fail union validation."""
    from core.config import VestaConfig

    monkeypatch.setenv("THINKING", '{"type":"adaptive"}')
    assert VestaConfig().thinking == {"type": "adaptive", "display": "summarized"}
    monkeypatch.setenv("THINKING", '{"type":"enabled"}')
    assert VestaConfig().thinking == {"type": "enabled", "budget_tokens": 10000}
    monkeypatch.setenv("THINKING", '{"type":"disabled"}')
    assert VestaConfig().thinking == {"type": "disabled"}


def test_thinking_string_form_still_parses(monkeypatch):
    from core.config import VestaConfig

    monkeypatch.setenv("THINKING", "adaptive")
    assert VestaConfig().thinking == {"type": "adaptive", "display": "summarized"}
    monkeypatch.setenv("THINKING", "disabled")
    assert VestaConfig().thinking == {"type": "disabled"}


def test_load_config_reverts_invalid_env_to_default(monkeypatch):
    """A malformed override must never crash the boot: the bad var drops to its default and is
    reported, instead of raising and crash-looping the container."""
    from core.config import load_config

    monkeypatch.setenv("RESPONSE_TIMEOUT", "not-a-number")
    config, issues = load_config()

    assert config.response_timeout == 600
    assert len(issues) == 1
    assert "RESPONSE_TIMEOUT" in issues[0]
    assert "RESPONSE_TIMEOUT" not in os.environ


def test_load_config_keeps_other_valid_overrides(monkeypatch):
    """Only the offending var is reverted; valid overrides alongside it survive."""
    from core.config import load_config

    monkeypatch.setenv("AGENT_MODEL", "sonnet")
    monkeypatch.setenv("NIGHTLY_MEMORY_HOUR", "99")
    config, issues = load_config()

    assert config.agent_model == "sonnet"
    assert config.nightly_memory_hour == 3
    assert len(issues) == 1
    assert "NIGHTLY_MEMORY_HOUR" in issues[0]


def test_load_config_clean_env_has_no_issues(monkeypatch):
    from core.config import load_config

    monkeypatch.setenv("AGENT_MODEL", "haiku")
    config, issues = load_config()

    assert config.agent_model == "haiku"
    assert issues == []


def test_report_config_issues_notifies_agent(config):
    """Config issues reach the agent as a core notification so it can tell the user."""
    import core.models as vm
    from core.loops import load_notifications
    from core.main import _report_config_issues

    _report_config_issues(["THINKING='bogus' is invalid (...); reverted to default"], config=config)

    notifs = asyncio.run(load_notifications(config=config))
    assert len(notifs) == 1
    assert notifs[0].type == vm.TYPE_CONFIG_INVALID
    body = notifs[0].body
    assert body is not None and "THINKING" in body


def test_report_config_issues_noop_without_issues(config):
    from core.main import _report_config_issues

    _report_config_issues([], config=config)
    assert not config.notifications_dir.exists() or list(config.notifications_dir.glob("*.json")) == []


# --- Config store + layered sources (writable store > env > shipped defaults floor) ---


import pytest  # noqa: E402


@pytest.fixture
def agentdir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    (tmp_path / "agent" / "data").mkdir(parents=True)
    return tmp_path / "agent"


def test_loads_shipped_defaults_with_no_env_or_store(agentdir, monkeypatch):
    # The crash class: none of model/provider/personality in env, no store -> defaults, no raise.
    import core.models as vm
    from core.config import load_config

    for key in ("AGENT_MODEL", "AGENT_PROVIDER", "AGENT_PERSONALITY", "AGENT_SEED_PERSONALITY"):
        monkeypatch.delenv(key, raising=False)
    config, issues = load_config()
    assert (config.agent_model, config.agent_provider, config.agent_personality) == ("opus", "claude", "dry")
    assert issues == []
    assert isinstance(config, vm.VestaConfig)


def test_store_overrides_env(agentdir, monkeypatch):
    import core.models as vm
    from core.config import update_config_store

    monkeypatch.setenv("AGENT_MODEL", "haiku")  # legacy env value
    update_config_store({"agent_model": "sonnet"})  # a PUT /config write
    assert vm.VestaConfig().agent_model == "sonnet"


def test_update_merges_and_clear_reverts(agentdir, monkeypatch):
    import core.models as vm
    from core.config import read_config_store, update_config_store

    monkeypatch.delenv("AGENT_MODEL", raising=False)
    update_config_store({"agent_model": "sonnet", "max_context_tokens": 500_000})
    assert read_config_store() == {"agent_model": "sonnet", "max_context_tokens": 500_000}
    # A None clears just that key; the other override stays.
    update_config_store({"max_context_tokens": None})
    assert read_config_store() == {"agent_model": "sonnet"}
    assert vm.VestaConfig().max_context_tokens is None


def test_update_rejects_non_writable_keys(agentdir):
    from core.config import update_config_store

    # Identity/auth must not be smuggled in through the settings path.
    with pytest.raises(ValueError):
        update_config_store({"agent_provider": "openrouter"})
    with pytest.raises(ValueError):
        update_config_store({"agent_token": "x"})


def test_corrupt_store_does_not_crash_load(agentdir, monkeypatch):
    from core.config import config_store_path, load_config, read_config_store

    config_store_path().write_text("{ not json")
    assert read_config_store() == {}
    for key in ("AGENT_MODEL", "AGENT_PROVIDER", "AGENT_PERSONALITY"):
        monkeypatch.delenv(key, raising=False)
    config, _ = load_config()
    assert config.agent_model == "opus"
