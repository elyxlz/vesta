"""Tests for subscription providers using Claude Code-compatible transports."""

import core.config as cfg
from core.client import KIMI_ANTHROPIC_URL, ZAI_ANTHROPIC_URL, build_client_options
from core.config import KimiConfig, OpenAIConfig, ZaiConfig


def test_build_client_options_routes_to_zai(tmp_path, state):
    config = cfg.VestaConfig(
        agent_dir=tmp_path / "agent",
        provider=ZaiConfig(
            model="glm-4.7",
            key="zai-secret",
            max_context_tokens=128_000,
        ),
    )
    config.agent_dir.mkdir(parents=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")

    options = build_client_options(config, state)

    assert options.model == "glm-4.7"
    assert options.env["ANTHROPIC_BASE_URL"] == ZAI_ANTHROPIC_URL
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "zai-secret"
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "128000"
    assert options.betas == []
    assert options.thinking is not None and options.thinking["type"] == "adaptive"


def test_build_client_options_routes_to_kimi(tmp_path, state):
    config = cfg.VestaConfig(
        agent_dir=tmp_path / "agent",
        provider=KimiConfig(model="kimi-for-coding", key="kimi-secret"),
    )
    config.agent_dir.mkdir(parents=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")

    options = build_client_options(config, state)

    assert options.model == "kimi-for-coding"
    assert options.env["ANTHROPIC_BASE_URL"] == KIMI_ANTHROPIC_URL
    assert options.env["ANTHROPIC_API_KEY"] == "kimi-secret"
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "262144"
    assert options.env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "262144"
    assert options.env["CLAUDE_CODE_SUBAGENT_MODEL"] == "kimi-for-coding"
    assert options.env["CLAUDE_CODE_EFFORT_LEVEL"] == "high"
    assert options.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "kimi-for-coding"
    assert options.betas == []
    assert options.thinking is not None and options.thinking["type"] == "adaptive"


def test_kimi_k3_uses_claude_context_hint_for_one_million_tokens(tmp_path, state):
    config = cfg.VestaConfig(
        agent_dir=tmp_path / "agent",
        provider=KimiConfig(model="k3", key="kimi-secret", max_context_tokens=1_048_576),
    )
    config.agent_dir.mkdir(parents=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")

    options = build_client_options(config, state)

    assert options.model == "k3[1m]"
    assert options.env["ANTHROPIC_MODEL"] == "k3[1m]"
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1048576"


def test_zai_glm_52_uses_claude_context_hint_for_one_million_tokens(tmp_path, state):
    config = cfg.VestaConfig(
        agent_dir=tmp_path / "agent",
        provider=ZaiConfig(model="glm-5.2", key="zai-secret", max_context_tokens=1_000_000),
    )
    config.agent_dir.mkdir(parents=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")

    options = build_client_options(config, state)

    assert options.model == "glm-5.2[1m]"
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1000000"
    assert options.env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "1000000"
    assert options.env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "glm-5.2[1m]"
    assert options.env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "glm-5.2[1m]"
    assert options.env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"


def test_zai_uses_catalog_context_when_api_omits_it(tmp_path, state):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", provider=ZaiConfig(model="glm-5.2", key="zai-secret"))
    config.agent_dir.mkdir(parents=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")

    options = build_client_options(config, state)

    assert options.model == "glm-5.2[1m]"
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "1000000"


def test_kimi_k3_defaults_to_the_all_tiers_256k_window(tmp_path, state):
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", provider=KimiConfig(model="k3", key="kimi-secret"))
    config.agent_dir.mkdir(parents=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")

    options = build_client_options(config, state)

    assert options.model == "k3"
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "262144"


def test_build_client_options_routes_openai_through_subscription_bridge(tmp_path, state):
    config = cfg.VestaConfig(
        agent_dir=tmp_path / "agent",
        provider=OpenAIConfig(model="gpt-5.6-sol", max_context_tokens=272_000),
    )
    config.agent_dir.mkdir(parents=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")
    state.codex_proxy_url = "http://127.0.0.1:18765"

    options = build_client_options(config, state)

    assert options.model == "gpt-5.6-sol[1m]"
    assert options.env["ANTHROPIC_BASE_URL"] == state.codex_proxy_url
    assert options.env["ANTHROPIC_AUTH_TOKEN"] == "unused"
    assert options.env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "272000"
    assert options.env["ANTHROPIC_SMALL_FAST_MODEL"] == "gpt-5.6-luna[1m]"
    assert options.env["CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK"] == "1"
    assert options.thinking is not None and options.thinking["type"] == "adaptive"
