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


def test_config_max_context_tokens_defaults_to_unset(tmp_path):
    """Unset (None) by default: Claude runs at its model default (1M via beta) and
    OpenRouter falls back to a 200k working cap. A chosen value overrides both."""
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    assert config.max_context_tokens is None


def test_config_max_context_tokens_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MAX_CONTEXT_TOKENS", "400000")
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    assert config.max_context_tokens == 400_000


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
    # Usage is reported against the resolved window, so the context-usage % is honest.
    assert options.context_window == 1_000_000


def test_build_client_options_openrouter_falls_back_when_unresolved(tmp_path, state):
    config = _config_with_memory(tmp_path, agent_provider="openrouter", agent_model="deepseek/deepseek-v4")
    state.openrouter_proxy_url = "http://127.0.0.1:40000"
    options = build_client_options(config, state)
    # No resolved window: claude-code keeps its own default (no env override) and usage is
    # reported against the conservative 200k fallback.
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in options.env
    assert options.context_window == 200_000


def test_build_client_options_claude_default_reports_1m_window(tmp_path, state):
    """A default Claude agent runs at the full 1M window: the beta is on and usage is reported
    against 1M directly (no conservative 200k under-reporting), with no explicit autocompact cap."""
    config = _config_with_memory(tmp_path)
    options = build_client_options(config, state)
    assert options.betas == ["context-1m-2025-08-07"]
    assert "CLAUDE_CODE_MAX_CONTEXT_TOKENS" not in options.env
    assert options.context_window == 1_000_000


def test_build_client_options_claude_caps_to_chosen_window(tmp_path, state):
    """A chosen window above 200k still needs the 1M beta, and reports against the chosen cap."""
    config = _config_with_memory(tmp_path, max_context_tokens=500_000)
    options = build_client_options(config, state)
    assert options.betas == ["context-1m-2025-08-07"]
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "500000"
    assert options.context_window == 500_000


def test_build_client_options_claude_200k_drops_beta(tmp_path, state):
    """A 200k window fits without the 1M beta, and reports against 200k."""
    config = _config_with_memory(tmp_path, max_context_tokens=200_000)
    options = build_client_options(config, state)
    assert options.betas == []
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "200000"
    assert options.context_window == 200_000
