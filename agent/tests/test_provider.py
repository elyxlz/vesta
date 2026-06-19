"""Tests for the agent's provider-auth state. Provider choice + OpenRouter key live in the config
store; the Claude OAuth blob lives in .credentials.json. These cover the Claude credentials auth
check (refresh-token-aware) and the boot/runtime state transitions."""

import json

import pytest

import core.models as vm
from core.config import read_config_store
from core.provider import (
    ProviderAuthState,
    _check_claude_auth,
    derive_status,
    observed_provider_failure,
    set_claude,
    set_openrouter,
)
from core.state_store import PersistedState, load_state


# --- Claude credentials auth check ---


def test_claude_auth_valid_access_token():
    creds = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    assert _check_claude_auth(creds)


def test_claude_auth_expired_with_refresh_token_still_passes():
    creds = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0, "refreshToken": "r"}})
    assert _check_claude_auth(creds)


def test_claude_auth_expired_no_refresh_fails():
    creds = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0}})
    assert not _check_claude_auth(creds)


def test_claude_auth_malformed_json_fails():
    assert not _check_claude_auth("not json")
    assert not _check_claude_auth("{}")
    assert not _check_claude_auth(json.dumps({"claudeAiOauth": None}))


# --- State transitions (free functions) ---


@pytest.fixture
def prov(tmp_path, monkeypatch, config):
    # Redirect the Claude credential paths into the tmp dir; the config store is already in the
    # config fixture's tmp AGENT_DIR. Returns (config, persisted).
    from core import provider as provider_mod

    home = tmp_path / "home"
    monkeypatch.setattr(provider_mod, "CREDENTIALS_PATH", home / ".claude" / ".credentials.json")
    monkeypatch.setattr(provider_mod, "CLAUDE_JSON_PATH", home / ".claude.json")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config, PersistedState()


def test_set_claude_writes_creds_and_store(prov):
    from core import provider as provider_mod

    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    status = set_claude(creds_json, config=config, persisted=persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "claude"
    assert provider_mod.CREDENTIALS_PATH.read_text() == creds_json
    assert read_config_store()["agent_provider"] == "claude"
    assert vm.VestaConfig().agent_provider == "claude"


def test_set_openrouter_writes_provider_key_and_model_to_store(prov):
    config, persisted = prov
    status = set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", config=config, persisted=persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "openrouter"
    assert status.model == "deepseek/deepseek-v4-flash"
    store = read_config_store()
    assert store["agent_provider"] == "openrouter"
    assert store["openrouter_key"] == "sk-or-v1-secret"
    assert store["agent_model"] == "deepseek/deepseek-v4-flash"
    # A fresh config (post-restart) reads the key as a SecretStr and re-derives as authenticated.
    fresh = vm.VestaConfig()
    assert fresh.openrouter_key is not None and fresh.openrouter_key.get_secret_value() == "sk-or-v1-secret"
    assert derive_status(fresh, persisted).kind == "openrouter"


def test_set_claude_clears_openrouter_key(prov):
    config, persisted = prov
    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", config=config, persisted=persisted)
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    set_claude(creds_json, config=config, persisted=persisted)
    store = read_config_store()
    assert store["agent_provider"] == "claude"
    assert "openrouter_key" not in store  # cleared, so no stale key leaks into OpenRouter mode


def test_observed_provider_failure_flips_and_persists(prov):
    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    status = set_claude(creds_json, config=config, persisted=persisted)
    observed_provider_failure(status, config=config, persisted=persisted)
    # Survives a restart: reload persisted state and re-derive.
    persisted2 = load_state(config)
    assert derive_status(vm.VestaConfig(), persisted2).state == ProviderAuthState.NOT_AUTHENTICATED


def test_boot_derives_authenticated_from_disk_when_no_persisted_state(prov):
    from core import provider as provider_mod

    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(creds_json)
    status = derive_status(config, persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "claude"


def test_boot_with_no_credentials_at_all_is_not_authenticated(prov):
    config, persisted = prov
    status = derive_status(config, persisted)
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.kind == "none"
