"""Tests for the agent's provider-auth state. The provider (model + key) lives nested in the config
store; the Claude OAuth blob lives in .credentials.json (loaded into the model at boot). These cover
the Claude credentials auth check (refresh-token-aware) and the boot/runtime state transitions."""

import json

import pydantic as pyd
import pytest

import core.config as cfg
from core.config import (
    ClaudeConfig,
    ClaudeOAuth,
    KimiConfig,
    OpenAIConfig,
    OpenRouterConfig,
    ZaiConfig,
    codex_proxy_auth_path,
    read_config_store,
    update_config_store,
)
from core.provider import (
    ProviderAuthState,
    UsageCredits,
    UsageError,
    _check_claude_oauth,
    _derive_kind_and_auth,
    clear_provider,
    derive_status,
    enforce_active_credentials,
    get_usage,
    is_terminal_auth_error,
    is_terminal_provider_error,
    observed_provider_failure,
    set_claude,
    set_key_provider,
    set_openai,
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


def test_derive_zai_authenticated_with_key():
    config = _cfg(ZaiConfig.model_validate({"model": "glm-4.7", "key": "zai-key"}))
    assert _derive_kind_and_auth(config) == ("zai", True)


def test_derive_kimi_authenticated_with_key():
    config = _cfg(KimiConfig.model_validate({"model": "kimi-for-coding", "key": "kimi-key"}))
    assert _derive_kind_and_auth(config) == ("kimi", True)


_CREDS = json.dumps({"claudeAiOauth": {"accessToken": "a", "expiresAt": 2**62}})
_OPENAI_CREDS = json.dumps({"access": "access", "refresh": "refresh", "expires": 2**62, "accountId": "acct"})


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


@pytest.mark.parametrize(
    "error,status,details,expected",
    [
        ("authentication_failed", None, ["API Error: 401 Invalid Authentication"], True),
        ("authentication_failed", None, ["API Error: 401 Your current subscription does not have access to k3"], False),
        ("authentication_failed", None, ["API Error: 401 Your current plan supports only kimi-k3 up to 256K context"], False),
        ("authentication_failed", None, ["API Error: 401 no access to kimi-for-coding-highspeed"], False),
        (None, 401, [], False),  # a bare Kimi status cannot distinguish auth from entitlement
        ("billing_error", None, ["unable to verify your membership benefits"], False),
    ],
)
def test_kimi_terminal_error_requires_an_explicit_invalid_credential_message(error, status, details, expected):
    assert is_terminal_provider_error("kimi", assistant_error=error, api_error_status=status, details=details) is expected


# --- Claude credentials auth check ---


@pytest.mark.parametrize(
    "oauth,expected",
    [
        ({"accessToken": "a", "expiresAt": 2**62}, True),  # valid, unexpired
        ({"accessToken": "a", "expiresAt": 0, "refreshToken": "r"}, True),  # expired but refreshable
        ({"accessToken": "a", "expiresAt": 0}, False),  # expired, no refresh
    ],
)
def test_claude_auth(oauth, expected):
    assert _check_claude_oauth(ClaudeOAuth.model_validate(oauth)) is expected


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
    assert provider_mod.CREDENTIALS_PATH.stat().st_mode & 0o777 == 0o600
    assert read_config_store()["provider"] == {"kind": "claude", "model": "opus"}
    assert isinstance(cfg.VestaConfig().provider, ClaudeConfig)


def test_set_openrouter_writes_nested_provider_to_store(prov):
    status = set_key_provider("openrouter", "sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)
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


def test_set_zai_writes_nested_provider_to_store(prov):
    status = set_key_provider("zai", "zai-secret", "glm-4.7", 128_000, config=prov)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "zai"
    assert read_config_store()["provider"] == {
        "kind": "zai",
        "model": "glm-4.7",
        "key": "zai-secret",
        "max_context_tokens": 128_000,
    }
    fresh = cfg.VestaConfig()
    assert isinstance(fresh.provider, ZaiConfig)
    assert derive_status(fresh).kind == "zai"


def test_set_kimi_writes_nested_provider_to_store(prov):
    status = set_key_provider("kimi", "kimi-secret", "kimi-for-coding", 128_000, config=prov)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "kimi"
    assert read_config_store()["provider"] == {
        "kind": "kimi",
        "model": "kimi-for-coding",
        "key": "kimi-secret",
        "max_context_tokens": 128_000,
    }
    fresh = cfg.VestaConfig()
    assert isinstance(fresh.provider, KimiConfig)
    assert derive_status(fresh).kind == "kimi"


def test_set_kimi_rejects_invalid_model_context_before_writing(prov):
    with pytest.raises(ValueError, match="kimi-for-coding supports at most 262144"):
        set_key_provider("kimi", "kimi-secret", "kimi-for-coding", 1_048_576, config=prov)
    assert read_config_store() == {}


def test_set_openai_writes_oauth_outside_config_store(prov):
    status = set_openai(_OPENAI_CREDS, "gpt-5.6-sol", 272_000, config=prov)
    assert status.state == ProviderAuthState.AUTHENTICATED
    assert status.kind == "openai"
    assert json.loads(codex_proxy_auth_path().read_text()) == json.loads(_OPENAI_CREDS)
    assert read_config_store()["provider"] == {
        "kind": "openai",
        "model": "gpt-5.6-sol",
        "max_context_tokens": 272_000,
    }
    fresh = cfg.VestaConfig()
    assert isinstance(fresh.provider, OpenAIConfig)
    assert derive_status(fresh).kind == "openai"
    assert codex_proxy_auth_path().stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "credentials",
    [
        "{}",
        "[]",
        json.dumps({"claudeAiOauth": {}}),
        json.dumps({"claudeAiOauth": {"expiresAt": 2**62}}),
        json.dumps({"claudeAiOauth": {"refreshToken": " "}}),
    ],
)
def test_set_claude_rejects_unusable_credentials_before_writing(prov, credentials):
    from core import provider as provider_mod

    with pytest.raises(ValueError):
        set_claude(credentials, "opus", None, config=prov)
    assert not provider_mod.CREDENTIALS_PATH.exists()
    assert read_config_store() == {}


def test_set_openai_rejects_invalid_context_before_writing_oauth(prov):
    with pytest.raises(ValueError, match="supports at most 272000"):
        set_openai(_OPENAI_CREDS, "gpt-5.6-sol", 300_000, config=prov)
    assert not codex_proxy_auth_path().exists()
    assert read_config_store() == {}


def test_set_openai_rejects_blank_tokens_before_writing_oauth(prov):
    credentials = json.dumps({"access": " ", "refresh": "refresh", "expires": 2**62})
    with pytest.raises(pyd.ValidationError):
        set_openai(credentials, "gpt-5.6-sol", None, config=prov)
    assert not codex_proxy_auth_path().exists()
    assert read_config_store() == {}


def test_switching_provider_removes_inactive_oauth_tokens(prov):
    from core import provider as provider_mod

    set_claude(_CREDS, "opus", None, config=prov)
    assert provider_mod.CREDENTIALS_PATH.exists()

    set_openai(_OPENAI_CREDS, "gpt-5.6-sol", None, config=cfg.VestaConfig())
    assert not provider_mod.CREDENTIALS_PATH.exists()
    assert codex_proxy_auth_path().exists()

    set_key_provider("kimi", "kimi-secret", "kimi-for-coding", None, config=cfg.VestaConfig())
    assert not provider_mod.CREDENTIALS_PATH.exists()
    assert not codex_proxy_auth_path().exists()


def test_provider_switch_rolls_back_config_and_credentials_on_write_failure(prov, monkeypatch):
    from core import provider as provider_mod

    set_claude(_CREDS, "opus", None, config=prov)
    old_store = read_config_store()

    def fail_persist(_provider):
        raise OSError("disk full")

    monkeypatch.setattr(provider_mod, "_persist_sign_in", fail_persist)
    with pytest.raises(OSError, match="disk full"):
        set_openai(_OPENAI_CREDS, "gpt-5.6-sol", None, config=cfg.VestaConfig())

    assert read_config_store() == old_store
    assert provider_mod.CREDENTIALS_PATH.read_text() == _CREDS
    assert not codex_proxy_auth_path().exists()


def test_boot_cleanup_skips_corrupt_or_fallback_provider_store(prov):
    from core import provider as provider_mod

    path = codex_proxy_auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_OPENAI_CREDS)

    cfg.config_store_path().write_text("{corrupt")
    enforce_active_credentials(cfg.VestaConfig.model_construct(provider=None))
    assert path.exists()

    update_config_store({"provider": {"kind": "openai", "model": "retired-openai-model"}})
    enforce_active_credentials(cfg.VestaConfig.model_construct(provider=ClaudeConfig()))
    assert path.exists()
    assert not provider_mod.CREDENTIALS_PATH.exists()


@pytest.mark.parametrize(
    "provider",
    [
        ZaiConfig(model="glm-4.7", key="zai-secret"),
        KimiConfig(model="kimi-for-coding", key="kimi-secret"),
    ],
)
def test_subscription_provider_keys_are_redacted_on_the_wire(provider):
    from core.config import stored_config

    config = _cfg(provider)
    dumped = stored_config(config)["provider"]
    assert isinstance(dumped, dict)
    assert dumped["key"] == "**********"


def test_model_context_prefs_persist_to_store_and_reload(prov):
    update_config_store({"provider": {"kind": "claude", "model": "opus", "max_context_tokens": 500_000}})
    provider = cfg.VestaConfig().provider
    assert isinstance(provider, ClaudeConfig)
    assert provider.model == "opus"
    assert provider.max_context_tokens == 500_000


def test_clear_provider_removes_creds_and_resets_state(prov):
    from core import provider as provider_mod

    # Seed both stores directly: normal provider switches now remove inactive credentials.
    provider_mod.CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    provider_mod.CREDENTIALS_PATH.write_text(_CREDS)
    codex_proxy_auth_path().parent.mkdir(parents=True, exist_ok=True)
    codex_proxy_auth_path().write_text(_OPENAI_CREDS)
    assert provider_mod.CREDENTIALS_PATH.exists()
    assert codex_proxy_auth_path().exists()

    status = clear_provider()
    assert status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert status.kind == "none"
    assert status.model is None
    assert not provider_mod.CREDENTIALS_PATH.exists()
    assert not codex_proxy_auth_path().exists()
    # Sign-out clears the provider entirely (no provider chosen), not a fake default.
    assert "provider" not in read_config_store()
    # A fresh boot re-derives unprovisioned from disk (no provider, creds removed).
    fresh = derive_status(cfg.VestaConfig())
    assert fresh.state == ProviderAuthState.NOT_AUTHENTICATED
    assert fresh.kind == "none"


def test_set_claude_replaces_openrouter_provider(prov):
    set_key_provider("openrouter", "sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)
    set_claude(_CREDS, "opus", None, config=prov)
    assert read_config_store()["provider"] == {"kind": "claude", "model": "opus"}  # no stale openrouter key leaks


def test_reauth_preserves_model_and_context(prov):
    # A re-auth sends no model/context; they must be preserved, not reset to defaults.
    update_config_store({"provider": {"kind": "claude", "model": "sonnet", "max_context_tokens": 500_000}})
    set_claude(_CREDS, None, None, config=prov)
    assert read_config_store()["provider"] == {"kind": "claude", "model": "sonnet", "max_context_tokens": 500_000}


def test_set_openrouter_applies_context_chosen_at_signin(prov):
    set_key_provider("openrouter", "sk-or-v1-secret", "deepseek/deepseek-v4-flash", 128_000, config=prov)
    assert read_config_store()["provider"] == {
        "kind": "openrouter",
        "model": "deepseek/deepseek-v4-flash",
        "key": "sk-or-v1-secret",
        "max_context_tokens": 128_000,
    }


def test_patch_provider_preserves_openrouter_key(prov):
    # Regression: a model-only PATCH must keep the real key, not the redacted '**********' from the dump.
    from core.config import validate_config_updates

    set_key_provider("openrouter", "sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)
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

    set_key_provider("openrouter", "sk-or-v1-secret", "deepseek/deepseek-v4-flash", None, config=prov)

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
