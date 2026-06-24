"""Tests for the agent's provider-auth state. Provider choice + OpenRouter key live in the config
store; the Claude OAuth blob lives in .credentials.json. These cover the Claude credentials auth
check (refresh-token-aware) and the boot/runtime state transitions."""

import json

import pytest

import core.models as vm
from core.config import read_config_store, update_config_store
from core.provider import (
    ProviderAuthState,
    UsageCredits,
    UsageError,
    _check_claude_auth,
    clear_provider,
    derive_status,
    get_usage,
    is_terminal_auth_error,
    observed_provider_failure,
    set_claude,
    set_openrouter,
)
from core.state_store import PersistedState, load_state


# --- Terminal auth-error classification (Claude path) ---


@pytest.mark.parametrize(
    "error,expected",
    [
        ("authentication_failed", True),  # 401, terminal
        ("billing_error", True),  # 402, terminal
        ("rate_limit", False),  # transient, resolves on retry
        ("server_error", False),  # transient (5xx)
        ("invalid_request", False),
        ("unknown", False),
        # A normal (non-error) turn carries error=None: the agent writing *about* a 401 in
        # conversation must never flip itself to unauthenticated.
        (None, False),
    ],
)
def test_is_terminal_auth_error(error, expected):
    assert is_terminal_auth_error(error) is expected


# --- Claude credentials auth check ---


@pytest.mark.parametrize(
    "creds,expected",
    [
        (json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}}), True),  # valid, unexpired
        (json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0, "refreshToken": "r"}}), True),  # expired but refreshable
        (json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0}}), False),  # expired, no refresh
        ("not json", False),
        ("{}", False),
        (json.dumps({"claudeAiOauth": None}), False),
    ],
)
def test_claude_auth(creds, expected):
    assert _check_claude_auth(creds) is expected


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


def test_model_context_prefs_persist_to_store_and_reload(prov):
    # Model/context are plain config keys now (PUT /config -> update_config_store); a fresh config
    # reads them back. This is the persistence the merged config surface relies on.
    update_config_store({"agent_model": "opus", "max_context_tokens": 500_000})
    store = read_config_store()
    assert store["agent_model"] == "opus"
    assert store["max_context_tokens"] == 500_000
    fresh = vm.VestaConfig()
    assert fresh.agent_model == "opus"
    assert fresh.max_context_tokens == 500_000


def test_clear_provider_removes_creds_and_key_and_flips_state(prov):
    from core import provider as provider_mod

    config, persisted = prov
    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", config=config, persisted=persisted)
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    set_claude(creds_json, config=config, persisted=persisted)
    assert provider_mod.CREDENTIALS_PATH.exists()

    status = clear_provider(config=config, persisted=persisted)
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.model is None
    assert not provider_mod.CREDENTIALS_PATH.exists()
    # Everything provider-owned is cleared (key + model + context); only the provider-choice hint stays.
    store = read_config_store()
    assert "openrouter_key" not in store
    assert "agent_model" not in store
    assert "max_context_tokens" not in store
    assert store["agent_provider"] == "claude"
    # A fresh boot re-derives not_authenticated (persisted), so the agent stays signed out.
    assert derive_status(vm.VestaConfig(), load_state(config)).state == ProviderAuthState.NOT_AUTHENTICATED


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


# --- model is only reported for an authenticated provider ---


def test_authenticated_provider_reports_model(prov):
    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    status = set_claude(creds_json, config=config, persisted=persisted)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.model == config.agent_model


def test_boot_derives_no_model_when_credentials_are_invalid(prov):
    from core import provider as provider_mod

    config, persisted = prov
    # Credentials on disk (so kind=claude) but unusable (expired, no refresh token) -> not authenticated.
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0}}))
    status = derive_status(config, persisted)
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.kind == "claude"
    assert status.model is None


def test_runtime_failure_clears_reported_model(prov):
    config, persisted = prov
    creds_json = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
    status = set_claude(creds_json, config=config, persisted=persisted)
    assert status.model is not None
    flipped = observed_provider_failure(status, config=config, persisted=persisted)
    assert flipped is not None and flipped.state == ProviderAuthState.NOT_AUTHENTICATED
    assert flipped.model is None


# --- provider-agnostic plan usage ---


def _write_claude_creds(provider_mod):
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok", "refreshToken": "r"}}))


@pytest.mark.anyio
async def test_get_usage_empty_when_no_provider(prov):
    config, _ = prov
    # No credentials on disk and no openrouter key -> kind none -> nothing to report (not an error).
    usage = await get_usage(config)
    assert usage.meters == []
    assert usage.credits is None


@pytest.mark.anyio
async def test_get_usage_claude_normalizes_buckets_and_credits(prov, monkeypatch):
    from core import provider as provider_mod

    config, _ = prov
    _write_claude_creds(provider_mod)
    sample = {
        "five_hour": {"utilization": 42, "resets_at": "2026-06-22T12:00:00Z"},
        "seven_day": {"utilization": 10, "resets_at": "2026-06-28T00:00:00Z"},
        "seven_day_opus": {"utilization": 5, "resets_at": "2026-06-28T00:00:00Z"},
        # cents upstream; normalized to dollars below.
        "extra_usage": {"is_enabled": True, "used_credits": 1234, "monthly_limit": 5000},
    }

    async def fake_fetch(url, *, headers):
        assert "oauth/usage" in url
        return sample

    monkeypatch.setattr(provider_mod, "_fetch_usage_json", fake_fetch)
    usage = await get_usage(config)
    assert [m.label for m in usage.meters] == ["current session", "current week", "current week (opus)"]
    assert usage.meters[0].used_pct == 42
    assert usage.meters[0].resets_at == "2026-06-22T12:00:00Z"
    assert usage.credits == UsageCredits(used=12.34, limit=50.0)


@pytest.mark.anyio
async def test_get_usage_openrouter_normalizes_credits(prov, monkeypatch):
    from core import provider as provider_mod

    config, persisted = prov
    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", config=config, persisted=persisted)
    fresh = vm.VestaConfig()

    async def fake_fetch(url, *, headers):
        assert url == provider_mod.OPENROUTER_KEY_URL
        return {"data": {"usage": 3.5, "limit": 10.0}}

    monkeypatch.setattr(provider_mod, "_fetch_usage_json", fake_fetch)
    usage = await get_usage(fresh)
    assert usage.meters == []
    assert usage.credits == UsageCredits(used=3.5, limit=10.0)


@pytest.mark.anyio
async def test_get_usage_propagates_fetch_error(prov, monkeypatch):
    from core import provider as provider_mod

    config, _ = prov
    _write_claude_creds(provider_mod)

    async def fake_fetch(url, *, headers):
        raise UsageError("upstream returned 500")

    monkeypatch.setattr(provider_mod, "_fetch_usage_json", fake_fetch)
    with pytest.raises(UsageError):
        await get_usage(config)
