"""Tests for subscription providers using Claude Code-compatible transports."""

import core.config as cfg
from core.client import KIMI_ANTHROPIC_URL, ZAI_ANTHROPIC_URL, build_client_options
from core.config import KimiConfig, ZaiConfig


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

