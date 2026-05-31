"""Tests for OpenRouter provider mode: config parsing and SDK option gating."""

import core.models as vm
from core.client import build_client_options


def test_config_parses_provider_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "openrouter")
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    assert config.agent_provider == "openrouter"


def test_config_defaults_to_claude(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    assert config.agent_provider == "claude"


def _config_with_memory(tmp_path, **overrides):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", **overrides)
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")
    return config


def test_build_client_options_keeps_anthropic_features_for_claude(tmp_path, state):
    config = _config_with_memory(tmp_path)
    options = build_client_options(config, state)
    assert options.betas == ["context-1m-2025-08-07"]
    thinking = options.thinking
    assert thinking is not None and thinking["type"] == "adaptive"


def test_build_client_options_drops_anthropic_features_for_openrouter(tmp_path, state):
    config = _config_with_memory(tmp_path, agent_provider="openrouter", agent_model="anthropic/claude-sonnet-4-6")
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    options = build_client_options(config, state)
    assert options.betas == []
    thinking = options.thinking
    assert thinking is not None and thinking["type"] == "disabled"
    assert options.model == "anthropic/claude-sonnet-4-6"
    # The SDK always points at the local caching proxy, never OpenRouter directly.
    assert options.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:40000"


def test_build_client_options_passes_resolved_context_window(tmp_path, state):
    config = _config_with_memory(tmp_path, agent_provider="openrouter", agent_model="deepseek/deepseek-v4")
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    state.openrouter_max_tokens = 1_000_000
    options = build_client_options(config, state)
    # Overrides claude-code's 200k default for non-Anthropic models (claude-code#46416).
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1000000"


def test_build_client_options_omits_context_window_when_unresolved(tmp_path, state):
    config = _config_with_memory(tmp_path, agent_provider="openrouter", agent_model="deepseek/deepseek-v4")
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    options = build_client_options(config, state)
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in options.env
