"""Tests for VestaConfig and initialization."""

import asyncio
import os

import pytest

import core.models as vm
from core.config import (
    VestaConfig,
    config_store_path,
    load_config,
    migrate_legacy_config_to_store,
    read_config_store,
    update_config_store,
)
from core.helpers import get_memory_path


def test_config_paths_under_agent_dir(config, tmp_path):
    assert config.notifications_dir.is_relative_to(config.agent_dir)
    assert config.data_dir.is_relative_to(config.agent_dir)
    assert config.logs_dir.is_relative_to(config.agent_dir)
    assert config.skills_dir.is_relative_to(config.agent_dir)


def test_config_default_values():
    config = vm.VestaConfig()
    assert config.monitor_tick_interval > 0
    assert config.response_timeout > 0


def test_memory_paths(config):
    assert get_memory_path(config) == config.agent_dir / "MEMORY.md"
    assert config.skills_dir == config.agent_dir / "skills"


# Both the plain-string form (THINKING=adaptive) and the legacy JSON-dict form written before
# adaptive.display was required (THINKING='{"type":"adaptive"}') must coerce to the SDK config.
@pytest.mark.parametrize(
    "value,expected",
    [
        ('{"type":"adaptive"}', {"type": "adaptive", "display": "summarized"}),
        ('{"type":"enabled"}', {"type": "enabled", "budget_tokens": 10000}),
        ('{"type":"disabled"}', {"type": "disabled"}),
        ("adaptive", {"type": "adaptive", "display": "summarized"}),
        ("disabled", {"type": "disabled"}),
    ],
)
def test_thinking_coerces(monkeypatch, value, expected):
    monkeypatch.setenv("THINKING", value)
    assert VestaConfig().thinking == expected


def test_load_config_reverts_invalid_env_to_default(monkeypatch):
    """A malformed override must never crash the boot: the bad var drops to its default and is
    reported, instead of raising and crash-looping the container."""
    monkeypatch.setenv("RESPONSE_TIMEOUT", "not-a-number")
    config, issues = load_config()

    assert config.response_timeout == 600
    assert len(issues) == 1
    assert "RESPONSE_TIMEOUT" in issues[0]
    assert "RESPONSE_TIMEOUT" not in os.environ


def test_load_config_keeps_other_valid_overrides(monkeypatch):
    """Only the offending var is reverted; valid overrides alongside it survive."""
    monkeypatch.setenv("AGENT_MODEL", "sonnet")
    monkeypatch.setenv("NIGHTLY_MEMORY_HOUR", "99")
    config, issues = load_config()

    assert config.agent_model == "sonnet"
    assert config.nightly_memory_hour == 3
    assert len(issues) == 1
    assert "NIGHTLY_MEMORY_HOUR" in issues[0]


def test_load_config_clean_env_has_no_issues(monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "haiku")
    config, issues = load_config()

    assert config.agent_model == "haiku"
    assert issues == []


def test_report_config_issues_notifies_agent(config):
    """Config issues reach the agent as a core notification so it can tell the user."""
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


@pytest.fixture
def agentdir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    (tmp_path / "agent" / "data").mkdir(parents=True)
    return tmp_path / "agent"


def test_loads_shipped_defaults_with_no_env_or_store(agentdir, monkeypatch):
    # The crash class: none of model/provider/personality in env, no store -> defaults, no raise.
    for key in ("AGENT_MODEL", "AGENT_PROVIDER", "AGENT_PERSONALITY", "AGENT_SEED_PERSONALITY"):
        monkeypatch.delenv(key, raising=False)
    config, issues = load_config()
    assert (config.agent_model, config.agent_provider, config.agent_personality) == ("opus", "claude", "dry")
    assert issues == []
    assert isinstance(config, vm.VestaConfig)


def test_store_overrides_env(agentdir, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "haiku")  # legacy env value
    update_config_store({"agent_model": "sonnet"})  # a PUT /config write
    assert vm.VestaConfig().agent_model == "sonnet"


def test_update_merges_and_clear_reverts(agentdir, monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    update_config_store({"agent_model": "sonnet", "max_context_tokens": 500_000})
    assert read_config_store() == {"agent_model": "sonnet", "max_context_tokens": 500_000}
    # A None clears just that key; the other override stays.
    update_config_store({"max_context_tokens": None})
    assert read_config_store() == {"agent_model": "sonnet"}
    assert vm.VestaConfig().max_context_tokens is None


def test_update_rejects_keys_that_are_not_config_fields(agentdir):
    # Any real VestaConfig field is writable; a key that isn't a field is a typo and is rejected
    # so it can't write a dead entry the loader would silently ignore.
    with pytest.raises(ValueError):
        update_config_store({"not_a_field": "x"})


def test_corrupt_store_does_not_crash_load(agentdir, monkeypatch):
    config_store_path().write_text("{ not json")
    assert read_config_store() == {}
    for key in ("AGENT_MODEL", "AGENT_PROVIDER", "AGENT_PERSONALITY"):
        monkeypatch.delenv(key, raising=False)
    config, _ = load_config()
    assert config.agent_model == "opus"


# --- Legacy fleet convergence onto the config store ---


def test_migrate_drains_genuine_env_values_into_store(agentdir, monkeypatch):
    monkeypatch.setenv("AGENT_MODEL", "sonnet")
    monkeypatch.setenv("AGENT_PERSONALITY", "warm")
    monkeypatch.setenv("MAX_CONTEXT_TOKENS", "500000")
    migrate_legacy_config_to_store()
    assert read_config_store() == {"agent_model": "sonnet", "agent_personality": "warm", "max_context_tokens": 500000}


def test_migrate_skips_keys_absent_from_env_no_default_lock_in(agentdir, monkeypatch):
    # Only the legacy AGENT_SEED_PERSONALITY is set (pre-rename); the alias is gone, so personality
    # must NOT be converged (else the default would be locked into the store).
    monkeypatch.delenv("AGENT_PERSONALITY", raising=False)
    monkeypatch.setenv("AGENT_SEED_PERSONALITY", "warm")
    monkeypatch.setenv("AGENT_MODEL", "opus")
    migrate_legacy_config_to_store()
    store = read_config_store()
    assert "agent_personality" not in store
    assert store["agent_model"] == "opus"


def test_migrate_does_not_overwrite_existing_store_and_is_idempotent(agentdir, monkeypatch):
    update_config_store({"agent_model": "haiku"})  # a prior PUT /config choice
    monkeypatch.setenv("AGENT_MODEL", "sonnet")  # legacy env says otherwise
    migrate_legacy_config_to_store()
    assert read_config_store()["agent_model"] == "haiku"  # PUT choice preserved
    migrate_legacy_config_to_store()  # second run is a no-op
    assert read_config_store()["agent_model"] == "haiku"


def test_migrate_ignores_nonnumeric_context(agentdir, monkeypatch):
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("AGENT_PERSONALITY", raising=False)
    monkeypatch.setenv("MAX_CONTEXT_TOKENS", "lots")
    migrate_legacy_config_to_store()
    assert "max_context_tokens" not in read_config_store()


def test_migrate_drains_legacy_provider_file_and_deletes_it(agentdir, monkeypatch, tmp_path):
    from core import config as config_mod

    for key in ("AGENT_MODEL", "AGENT_PERSONALITY", "MAX_CONTEXT_TOKENS"):
        monkeypatch.delenv(key, raising=False)
    legacy = tmp_path / "vesta-provider.env"
    legacy.write_text(
        "export AGENT_PROVIDER=openrouter\n"
        "export AGENT_MODEL='deepseek/deepseek-v4-flash'\n"
        "export ANTHROPIC_AUTH_TOKEN='sk-or-v1-secret'\n"
        "export MAX_CONTEXT_TOKENS=200000\n"
    )
    monkeypatch.setattr(config_mod, "_LEGACY_PROVIDER_ENV", legacy)

    config_mod.migrate_legacy_config_to_store()
    store = config_mod.read_config_store()
    assert store["agent_provider"] == "openrouter"
    assert store["agent_model"] == "deepseek/deepseek-v4-flash"
    assert store["openrouter_key"] == "sk-or-v1-secret"
    assert store["max_context_tokens"] == 200000
    assert not legacy.exists()  # the legacy file is retired after draining


def test_migrate_legacy_claude_file_carries_no_key(agentdir, monkeypatch, tmp_path):
    from core import config as config_mod

    for key in ("AGENT_MODEL", "AGENT_PERSONALITY", "MAX_CONTEXT_TOKENS"):
        monkeypatch.delenv(key, raising=False)
    legacy = tmp_path / "vesta-provider.env"
    legacy.write_text("export AGENT_PROVIDER=claude\nexport ANTHROPIC_AUTH_TOKEN=\n")
    monkeypatch.setattr(config_mod, "_LEGACY_PROVIDER_ENV", legacy)

    config_mod.migrate_legacy_config_to_store()
    store = config_mod.read_config_store()
    assert store["agent_provider"] == "claude"
    assert "openrouter_key" not in store
    assert not legacy.exists()
