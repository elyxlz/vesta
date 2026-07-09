"""Tests for the agent's provider-auth state. The provider (model + key) lives nested in the config
store; the Claude OAuth blob lives in .credentials.json (loaded into the model at boot). These cover
the Claude credentials auth check (refresh-token-aware) and the boot/runtime state transitions."""

import json

import pytest

import core.config as cfg
from core.config import ClaudeConfig, ClaudeOAuth, OpenRouterConfig, read_config_store, update_config_store
from core.provider import (
    ProviderAuthState,
    UsageCredits,
    UsageError,
    _check_claude_auth,
    _derive_kind_and_auth,
    clear_provider,
    derive_status,
    get_usage,
    is_terminal_auth_error,
    observed_provider_failure,
    set_claude,
    set_openrouter,
)


def _cfg(provider):
    return cfg.VestaConfig.model_construct(provider=provider)


# --- Honest derivation: unprovisioned vs set-but-unauthenticated vs authenticated ---


def test_derive_none_when_no_provider_chosen():
    assert _derive_kind_and_auth(_cfg(None)) == ("none", False)


def test_derive_claude_unauthenticated_when_oauth_invalid():
    # Provider SET to claude (a real choice) but the OAuth blob is expired with no refresh token.
    expired = ClaudeOAuth(accessToken="x", refreshToken=None, expiresAt=1)
    assert _derive_kind_and_auth(_cfg(ClaudeConfig(oauth=expired))) == ("claude", False)


def test_derive_claude_authenticated_when_oauth_refreshable():
    refreshable = ClaudeOAuth(accessToken="x", refreshToken="r", expiresAt=0)
    assert _derive_kind_and_auth(_cfg(ClaudeConfig(oauth=refreshable))) == ("claude", True)


def test_derive_openrouter_authenticated_with_key():
    cfg = _cfg(OpenRouterConfig.model_validate({"model": "m", "key": "sk-or-v1-x"}))
    assert _derive_kind_and_auth(cfg) == ("openrouter", True)


_CREDS = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})


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
        (None, False),  # a normal turn must never flip the agent to unauthenticated
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
    # Redirect the Claude credential paths into the tmp dir. The OAuth blob is hydrated into the model
    # from config.CREDENTIALS_PATH, and set_claude writes provider.CREDENTIALS_PATH, so both must point
    # at the same tmp path. The config store already lives in the config fixture's tmp AGENT_DIR.
    from core import config as config_mod
    from core import provider as provider_mod

    creds_path = tmp_path / "home" / ".claude" / ".credentials.json"
    monkeypatch.setattr(config_mod, "CREDENTIALS_PATH", creds_path)
    monkeypatch.setattr(provider_mod, "CREDENTIALS_PATH", creds_path)
    monkeypatch.setattr(provider_mod, "CLAUDE_JSON_PATH", tmp_path / "home" / ".claude.json")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    return config


def test_set_claude_writes_creds_and_store(prov):
    from core import provider as provider_mod

    status = set_claude(_CREDS, "opus", None, config=prov)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "claude"
    assert provider_mod.CREDENTIALS_PATH.read_text() == _CREDS
    assert read_config_store()["provider"] == {"kind": "claude", "model": "opus"}
    assert isinstance(cfg.VestaConfig().provider, ClaudeConfig)


def test_set_openrouter_writes_nested_provider_to_store(prov):
    status = set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "openrouter"
    assert status.model == "deepseek/deepseek-v4-flash"
    assert read_config_store()["provider"] == {
        "kind": "openrouter",
        "model": "deepseek/deepseek-v4-flash",
        "key": "sk-or-v1-secret",
    }
    # A fresh config (post-restart) reads the key as a SecretStr and re-derives as authenticated.
    fresh = cfg.VestaConfig()
    assert isinstance(fresh.provider, OpenRouterConfig)
    assert fresh.provider.key.get_secret_value() == "sk-or-v1-secret"
    assert derive_status(fresh).kind == "openrouter"


def test_model_context_prefs_persist_to_store_and_reload(prov):
    update_config_store({"provider": {"kind": "claude", "model": "opus", "max_context_tokens": 500_000}})
    provider = cfg.VestaConfig().provider
    assert isinstance(provider, ClaudeConfig)
    assert provider.model == "opus"
    assert provider.max_context_tokens == 500_000


def test_clear_provider_removes_creds_and_resets_state(prov):
    from core import provider as provider_mod

    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)
    set_claude(_CREDS, "opus", None, config=prov)
    assert provider_mod.CREDENTIALS_PATH.exists()

    status = clear_provider(config=prov)
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.kind == "none"
    assert status.model is None
    assert not provider_mod.CREDENTIALS_PATH.exists()
    # Sign-out clears the provider entirely (no provider chosen), not a fake default.
    assert "provider" not in read_config_store()
    # A fresh boot re-derives unprovisioned from disk (no provider, creds removed).
    fresh = derive_status(cfg.VestaConfig())
    assert fresh.state == ProviderAuthState.NOT_AUTHENTICATED
    assert fresh.kind == "none"


def test_set_claude_replaces_openrouter_provider(prov):
    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)
    set_claude(_CREDS, "opus", None, config=prov)
    assert read_config_store()["provider"] == {"kind": "claude", "model": "opus"}  # no stale openrouter key leaks


def test_reauth_preserves_model_and_context(prov):
    # `vesta auth` re-auth sends no model/context; they must be preserved, not reset to defaults.
    update_config_store({"provider": {"kind": "claude", "model": "sonnet", "max_context_tokens": 500_000}})
    set_claude(_CREDS, None, None, config=prov)
    assert read_config_store()["provider"] == {"kind": "claude", "model": "sonnet", "max_context_tokens": 500_000}


def test_set_openrouter_applies_context_chosen_at_signin(prov):
    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", 128_000, config=prov)
    assert read_config_store()["provider"] == {
        "kind": "openrouter",
        "model": "deepseek/deepseek-v4-flash",
        "key": "sk-or-v1-secret",
        "max_context_tokens": 128_000,
    }


def test_patch_provider_preserves_openrouter_key(prov):
    # Regression: a model-only PATCH must keep the real key, not the redacted '**********' from the dump.
    from core.config import validate_config_updates

    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)
    updates = validate_config_updates(cfg.VestaConfig(), {"provider": {"model": "anthropic/claude-3"}})
    assert updates["provider"] == {"kind": "openrouter", "model": "anthropic/claude-3", "key": "sk-or-v1-secret"}


def test_observed_provider_failure_flips_in_memory_only(prov):
    from core import provider as provider_mod

    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(_CREDS)
    status = set_claude(_CREDS, "opus", None, config=prov)
    flipped = observed_provider_failure(status)
    assert flipped is not None and flipped.state == ProviderAuthState.NOT_AUTHENTICATED
    # It does NOT persist: a fresh boot re-derives optimistically from disk (creds still present).
    assert derive_status(cfg.VestaConfig()).state == ProviderAuthState.AUTHENTICATED


def test_boot_derives_authenticated_from_disk_when_no_persisted_state(prov):
    from core import provider as provider_mod

    # A signed-in Claude agent: the chosen provider in the store + valid creds on disk.
    update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(_CREDS)
    status = derive_status(cfg.VestaConfig())
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "claude"


def test_boot_with_no_credentials_at_all_is_not_authenticated(prov):
    status = derive_status(cfg.VestaConfig())
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.kind == "none"


# --- model is only reported for an authenticated provider ---


def test_authenticated_provider_reports_model(prov):
    status = set_claude(_CREDS, "opus", None, config=prov)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.model == "opus"


def test_boot_derives_no_model_when_credentials_are_invalid(prov):
    from core import provider as provider_mod

    # Claude chosen in the store, but the creds on disk are unusable (expired, no refresh token) ->
    # set-but-unauthenticated: kind stays claude, state not_authenticated.
    update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 0}}))
    status = derive_status(cfg.VestaConfig())
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.kind == "claude"
    assert status.model is None


def test_runtime_failure_clears_reported_model(prov):
    status = set_claude(_CREDS, "opus", None, config=prov)
    assert status.model is not None
    flipped = observed_provider_failure(status)
    assert flipped is not None and flipped.state == ProviderAuthState.NOT_AUTHENTICATED
    assert flipped.model is None


# --- provider-agnostic plan usage ---


@pytest.mark.anyio
async def test_get_usage_empty_when_no_provider(prov):
    # No credentials on disk and no openrouter key -> kind none -> nothing to report (not an error).
    usage = await get_usage(cfg.VestaConfig())
    assert usage.meters == []
    assert usage.credits is None


@pytest.mark.anyio
async def test_get_usage_claude_normalizes_buckets_and_credits(prov, monkeypatch):
    from core import provider as provider_mod

    update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok", "refreshToken": "r"}}))
    sample = {
        "five_hour": {"utilization": 42, "resets_at": "2026-06-22T12:00:00Z"},
        "seven_day": {"utilization": 10, "resets_at": "2026-06-28T00:00:00Z"},
        "seven_day_opus": {"utilization": 5, "resets_at": "2026-06-28T00:00:00Z"},
        "extra_usage": {"is_enabled": True, "used_credits": 1234, "monthly_limit": 5000},
    }

    async def fake_fetch(url, *, headers):
        assert "oauth/usage" in url
        return sample

    monkeypatch.setattr(provider_mod, "_fetch_usage_json", fake_fetch)
    usage = await get_usage(cfg.VestaConfig())
    assert [m.label for m in usage.meters] == ["current session", "current week", "current week (opus)"]
    assert usage.meters[0].used_pct == 42
    assert usage.meters[0].resets_at == "2026-06-22T12:00:00Z"
    assert usage.credits == UsageCredits(used=12.34, limit=50.0)


@pytest.mark.anyio
async def test_get_usage_openrouter_normalizes_credits(prov, monkeypatch):
    from core import provider as provider_mod

    set_openrouter("sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)

    async def fake_fetch(url, *, headers):
        assert url == provider_mod.OPENROUTER_KEY_URL
        return {"data": {"usage": 3.5, "limit": 10.0}}

    monkeypatch.setattr(provider_mod, "_fetch_usage_json", fake_fetch)
    usage = await get_usage(cfg.VestaConfig())
    assert usage.meters == []
    assert usage.credits == UsageCredits(used=3.5, limit=10.0)


@pytest.mark.anyio
async def test_get_usage_propagates_fetch_error(prov, monkeypatch):
    from core import provider as provider_mod

    update_config_store({"provider": {"kind": "claude", "model": "opus"}})
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok", "refreshToken": "r"}}))

    async def fake_fetch(url, *, headers):
        raise UsageError("upstream returned 500")

    monkeypatch.setattr(provider_mod, "_fetch_usage_json", fake_fetch)
    with pytest.raises(UsageError):
        await get_usage(cfg.VestaConfig())
