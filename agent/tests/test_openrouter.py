"""Tests for OpenRouter provider mode: nested provider config and SDK option gating."""

import pytest

import core.config as cfg
from core.client import build_client_options, resolve_openrouter_max_tokens
from core.config import ClaudeConfig, OpenRouterConfig


def test_config_accepts_openrouter_provider(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", provider=OpenRouterConfig.model_validate({"model": "x/y", "key": "sk-test"}))
    assert isinstance(config.provider, OpenRouterConfig)
    assert config.provider.kind == "openrouter"


def test_config_defaults_to_no_provider(tmp_path):
    # A fresh agent has no provider chosen yet (distinct from a chosen-but-unauthenticated provider).
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    assert config.provider is None


def test_config_max_context_tokens_defaults_to_unset(tmp_path):
    """Unset (None) by default on a chosen provider: Claude runs at its model default (1M via beta) and
    OpenRouter falls back to a 200k working cap. A chosen value overrides both."""
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", provider=ClaudeConfig(model="opus"))
    assert isinstance(config.provider, ClaudeConfig)
    assert config.provider.max_context_tokens is None


def test_config_provider_carries_max_context_tokens(tmp_path):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", provider=ClaudeConfig(model="opus", max_context_tokens=400_000))
    assert isinstance(config.provider, ClaudeConfig)
    assert config.provider.max_context_tokens == 400_000


def _config_with_memory(tmp_path, *, provider=None):
    # build_client_options requires a chosen provider; default to Claude when a test doesn't pin one.
    config = cfg.VestaConfig(
        agent_dir=tmp_path / "agent",
        provider=provider if provider is not None else ClaudeConfig(),
    )
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")
    return config


def _openrouter(model):
    return {"kind": "openrouter", "model": model, "key": "sk-or-test"}


def test_build_client_options_keeps_anthropic_features_for_claude(tmp_path, state):
    config = _config_with_memory(tmp_path)
    options = build_client_options(config, state)
    assert options.betas == ["context-1m-2025-08-07"]
    thinking = options.thinking
    assert thinking is not None and thinking["type"] == "adaptive"


def test_build_client_options_drops_anthropic_features_for_openrouter(tmp_path, state):
    config = _config_with_memory(tmp_path, provider=_openrouter("anthropic/claude-sonnet-4-6"))
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    options = build_client_options(config, state)
    assert options.betas == []
    thinking = options.thinking
    assert thinking is not None and thinking["type"] == "disabled"
    assert options.model == "anthropic/claude-sonnet-4-6"
    # The SDK always points at the local caching proxy, never OpenRouter directly; the union guarantees the key.
    assert options.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:40000"
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "sk-or-test"


def test_build_client_options_passes_resolved_context_window(tmp_path, state):
    config = _config_with_memory(tmp_path, provider=_openrouter("deepseek/deepseek-v4"))
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    state.openrouter_max_tokens = 1_000_000
    options = build_client_options(config, state)
    # Overrides claude-code's 200k default for non-Anthropic models (claude-code#46416).
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1000000"


def test_build_client_options_openrouter_falls_back_when_unresolved(tmp_path, state):
    config = _config_with_memory(tmp_path, provider=_openrouter("deepseek/deepseek-v4"))
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    options = build_client_options(config, state)
    # No resolved window: claude-code keeps its own default (no env override).
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in options.env


def test_build_client_options_preserves_explicit_cap_before_resolution(tmp_path, state):
    config = _config_with_memory(
        tmp_path,
        provider=OpenRouterConfig(model="deepseek/deepseek-v4", key="key", max_context_tokens=64_000),
    )
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    options = build_client_options(config, state)
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "64000"


class _ModelResponse:
    def __init__(self, status, body):
        self.status = status
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self):
        return self.body


class _ModelSession:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get(self, *_args, **_kwargs):
        return self.response


@pytest.mark.anyio
async def test_openrouter_context_resolver_uses_selected_model_metadata(tmp_path, monkeypatch):
    import core.client as client_mod

    config = _config_with_memory(tmp_path, provider=_openrouter("vendor/model"))
    response = _ModelResponse(200, {"data": [{"id": "other/model", "context_length": 1}, {"id": "vendor/model", "context_length": 131_072}]})
    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", lambda: _ModelSession(response))
    assert await resolve_openrouter_max_tokens(config) == 131_072


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,body,match",
    [
        (503, {}, "HTTP 503"),
        (200, {"data": [{"id": "other/model", "context_length": 100_000}]}, "no valid context_length"),
        (200, {"data": [{"id": "vendor/model", "context_length": "large"}]}, "no valid context_length"),
    ],
)
async def test_openrouter_context_resolver_fails_closed_on_bad_metadata(tmp_path, monkeypatch, status, body, match):
    import core.client as client_mod

    config = _config_with_memory(tmp_path, provider=_openrouter("vendor/model"))
    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", lambda: _ModelSession(_ModelResponse(status, body)))
    with pytest.raises(RuntimeError, match=match):
        await resolve_openrouter_max_tokens(config)


def test_build_client_options_claude_default_reports_1m_window(tmp_path, state):
    """A default Claude agent runs at the full 1M window: the beta is on, no explicit autocompact cap."""
    config = _config_with_memory(tmp_path)
    options = build_client_options(config, state)
    assert options.betas == ["context-1m-2025-08-07"]
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in options.env


def test_build_client_options_claude_caps_to_chosen_window(tmp_path, state):
    """A chosen window above 200k still needs the 1M beta, and reports against the chosen cap."""
    config = _config_with_memory(tmp_path, provider={"kind": "claude", "model": "opus", "max_context_tokens": 500_000})
    options = build_client_options(config, state)
    assert options.betas == ["context-1m-2025-08-07"]
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "500000"


def test_build_client_options_claude_200k_drops_beta(tmp_path, state):
    """A 200k window fits without the 1M beta, and reports against 200k."""
    config = _config_with_memory(tmp_path, provider={"kind": "claude", "model": "opus", "max_context_tokens": 200_000})
    options = build_client_options(config, state)
    assert options.betas == []
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "200000"
