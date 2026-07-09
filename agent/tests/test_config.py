"""Tests for VestaConfig and initialization."""

import json
import os
import pathlib as pl

import pytest

import core.models as vm
from core.config import (
    ClaudeConfig,
    config_store_path,
    load_config,
    load_notification_rules,
    migrate_notification_policy_file,
    read_config_store,
    update_config_store,
    validate_config_updates,
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


def test_default_provider_is_none_when_unprovisioned(agentdir, monkeypatch, tmp_path):
    """A fresh agent (no store, no legacy file, no creds) has no provider chosen at all."""
    from core import config as config_mod

    monkeypatch.setattr(config_mod, "CREDENTIALS_PATH", tmp_path / ".credentials.json")
    config, _ = config_mod.load_config()
    assert config.provider is None


# Both the plain-string form (thinking="adaptive") and the legacy JSON-dict form written before
# adaptive.display was required must coerce to the SDK config. thinking lives on the claude provider.
@pytest.mark.parametrize(
    "value,expected",
    [
        ({"type": "adaptive"}, {"type": "adaptive", "display": "summarized"}),
        ({"type": "enabled"}, {"type": "enabled", "budget_tokens": 10000}),
        ({"type": "disabled"}, {"type": "disabled"}),
        ("adaptive", {"type": "adaptive", "display": "summarized"}),
        ("disabled", {"type": "disabled"}),
    ],
)
def test_thinking_coerces(value, expected):
    assert ClaudeConfig(thinking=value).thinking == expected


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
    monkeypatch.setenv("RESPONSE_TIMEOUT", "300")
    monkeypatch.setenv("NIGHTLY_MEMORY_HOUR", "99")
    config, issues = load_config()

    assert config.response_timeout == 300
    assert config.nightly_memory_hour == 3
    assert len(issues) == 1
    assert "NIGHTLY_MEMORY_HOUR" in issues[0]


def test_load_config_clean_env_has_no_issues(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    config, issues = load_config()

    assert config.log_level == "DEBUG"
    assert issues == []


def test_config_issues_turn_tells_agent(config):
    """Config issues reach the agent as a boot-turn body so it can tell the user."""
    from core.main import config_issues_turn

    body = config_issues_turn(["THINKING='bogus' is invalid (...); reverted to default"], config=config)

    assert body is not None
    assert "THINKING" in body
    assert "restart_vesta" in body


def test_config_issues_turn_noop_without_issues(config):
    from core.main import config_issues_turn

    assert config_issues_turn([], config=config) is None


# --- Config store (nested provider + scalar prefs) ---


@pytest.fixture
def agentdir(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DIR", str(tmp_path / "agent"))
    (tmp_path / "agent" / "data").mkdir(parents=True)
    return tmp_path / "agent"


def test_loads_shipped_defaults_with_no_env_or_store(agentdir, monkeypatch, tmp_path):
    # The crash class: nothing in env, no store -> field defaults (provider unchosen), no raise.
    from core import config as config_mod

    monkeypatch.setattr(config_mod, "CREDENTIALS_PATH", tmp_path / ".credentials.json")
    config, issues = load_config()
    assert config.provider is None
    assert config.agent_personality == "dry"
    assert issues == []
    assert isinstance(config, vm.VestaConfig)


def test_store_sets_nested_provider(agentdir):
    update_config_store({"provider": {"kind": "claude", "model": "sonnet"}})
    provider = vm.VestaConfig().provider
    assert isinstance(provider, ClaudeConfig)
    assert provider.model == "sonnet"


def test_update_merges_and_clear_reverts(agentdir):
    update_config_store({"provider": {"kind": "claude", "model": "sonnet"}, "agent_personality": "warm"})
    assert read_config_store() == {"provider": {"kind": "claude", "model": "sonnet"}, "agent_personality": "warm"}
    # A None clears just that key; the provider override stays.
    update_config_store({"agent_personality": None})
    assert read_config_store() == {"provider": {"kind": "claude", "model": "sonnet"}}
    assert vm.VestaConfig().agent_personality == "dry"


def test_update_rejects_keys_that_are_not_config_fields(agentdir):
    with pytest.raises(ValueError):
        update_config_store({"not_a_field": "x"})


def test_corrupt_store_does_not_crash_load(agentdir, monkeypatch, tmp_path):
    from core import config as config_mod

    monkeypatch.setattr(config_mod, "CREDENTIALS_PATH", tmp_path / ".credentials.json")
    config_store_path().write_text("{ not json")
    assert read_config_store() == {}
    config, _ = load_config()
    assert config.provider is None


def _deny_read_text(self, *args, **kwargs):
    raise PermissionError("permission denied")


def test_unreadable_store_does_not_crash_read(agentdir, monkeypatch):
    # An OSError on the read (permission flip, transient IO fault) is ignored like corruption:
    # read_config_store sits on the boot path and never raises.
    config_store_path().write_text("{}")
    monkeypatch.setattr(pl.Path, "read_text", _deny_read_text)
    assert read_config_store() == {}


def test_unreadable_store_does_not_crash_rules_load(agentdir, monkeypatch):
    # load_notification_rules runs on monitor_loop's per-tick hot path; an unreadable store must
    # yield no rules, never an exception that kills notification processing.
    update_config_store({"notification_rules": [{"id": "a", "source": "twitter", "action": "pool"}]})
    config = vm.VestaConfig()
    monkeypatch.setattr(pl.Path, "read_text", _deny_read_text)
    assert load_notification_rules(config) == []


def test_stored_config_serializes_null_provider(agentdir, monkeypatch, tmp_path):
    from core import config as config_mod
    from core.config import stored_config

    monkeypatch.setattr(config_mod, "CREDENTIALS_PATH", tmp_path / ".credentials.json")
    config, _ = config_mod.load_config()
    assert stored_config(config)["provider"] is None


# --- PUT /config (prefs) + PATCH /provider validation ---


@pytest.mark.parametrize("key", ["openrouter_key", "agent_provider", "agent_model", "max_context_tokens", "thinking"])
def test_validate_config_rejects_non_pref_keys(config, key):
    # Flat provider keys are not config fields anymore; the provider is set via /provider.
    with pytest.raises(ValueError, match="not config fields"):
        validate_config_updates(config, {key: "x"})


@pytest.mark.parametrize(
    "key,value",
    [
        ("agent_personality", "playful"),
        ("timezone", "Europe/London"),
        ("seed_context", "they like terse replies"),
    ],
)
def test_validate_config_accepts_every_preference(config, key, value):
    assert validate_config_updates(config, {key: value}) == {key: value}


def test_validate_provider_partial_deep_merges(config):
    # A provider partial (PATCH /provider) merges onto the current provider and revalidates. PATCH only
    # applies to an already-chosen provider, so seed one in the store first.
    update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    updates = validate_config_updates(config, {"provider": {"model": "sonnet"}})
    assert updates["provider"] == {"kind": "claude", "model": "sonnet"}


def test_config_applies_timezone_to_process_env(monkeypatch):
    # The config object owns timezone: constructing it pushes the value into TZ so every child
    # process (shell, calendar/reminders skills, tasks' tzlocal) inherits it.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    config = vm.VestaConfig()
    assert config.timezone == "Asia/Tokyo"
    assert os.environ["TZ"] == "Asia/Tokyo"


# --- migrate_notification_policy_file (legacy notification_policy.json -> notification_rules) ---


def _write_legacy_policy(agentdir, policy):
    (agentdir / "data" / "notification_policy.json").write_text(json.dumps(policy))


def test_migrate_policy_folds_rules_and_deletes_file(agentdir):
    _write_legacy_policy(agentdir, {"rules": [{"id": "a", "source": "twitter", "action": "pool"}]})
    migrate_notification_policy_file()
    assert "notification_rules" in read_config_store()
    assert [rule.source for rule in load_notification_rules(vm.VestaConfig())] == ["twitter"]
    assert not (agentdir / "data" / "notification_policy.json").exists()


def test_migrate_policy_translates_defaults_into_trailing_rules(agentdir):
    # A default with an empty type becomes a source-only rule; a concrete type is preserved. Defaults
    # were consulted after rules, so they trail; every migrated rule gets an id.
    _write_legacy_policy(
        agentdir,
        {
            "rules": [{"source": "twitter", "action": "interrupt"}],
            "defaults": [
                {"source": "outlook", "type": "", "action": "pool"},
                {"source": "calendar", "type": "reminder", "action": "pool"},
            ],
        },
    )
    migrate_notification_policy_file()
    rules = load_notification_rules(vm.VestaConfig())
    assert [(rule.source, rule.type, rule.action) for rule in rules] == [
        ("twitter", None, "interrupt"),
        ("outlook", None, "pool"),
        ("calendar", "reminder", "pool"),
    ]
    assert all(rule.id for rule in rules)


def test_migrate_policy_no_file_is_a_noop(agentdir):
    migrate_notification_policy_file()
    assert "notification_rules" not in read_config_store()


def test_migrate_policy_does_not_overwrite_existing_rules(agentdir):
    update_config_store({"notification_rules": [{"id": "keep", "source": "existing", "action": "pool"}]})
    _write_legacy_policy(agentdir, {"rules": [{"source": "twitter", "action": "interrupt"}]})
    migrate_notification_policy_file()
    assert [rule.source for rule in load_notification_rules(vm.VestaConfig())] == ["existing"]
    assert not (agentdir / "data" / "notification_policy.json").exists()
