"""The constitution is a user-authored charter prepended to the system prompt ahead
of MEMORY.md. It is bind-mounted read-only into the container, so the agent reads it
but cannot edit it; these tests cover the prompt-assembly side."""

import core.config as cfg
from core.client import build_client_options
from core.config import ClaudeConfig


def _config(tmp_path, **overrides):
    # build_client_options requires a chosen provider; default to Claude for these prompt-assembly tests.
    overrides.setdefault("provider", ClaudeConfig())
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent", **overrides)
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("my memory body")
    return config


def _system_prompt(config, state) -> str:
    prompt = build_client_options(config, state).system_prompt
    assert isinstance(prompt, str)
    return prompt


def test_constitution_is_prepended_ahead_of_memory(tmp_path, state):
    config = _config(tmp_path)
    (config.agent_dir / "constitution.md").write_text("Always tell the truth.")
    prompt = _system_prompt(config, state)
    assert "Always tell the truth." in prompt
    assert prompt.index("Always tell the truth.") < prompt.index("my memory body")
    assert "immutable" in prompt.lower()


def test_no_constitution_file_leaves_prompt_unchanged(tmp_path, state):
    config = _config(tmp_path)
    prompt = _system_prompt(config, state)
    assert "Constitution" not in prompt
    assert "my memory body" in prompt


def test_empty_constitution_is_ignored(tmp_path, state):
    config = _config(tmp_path)
    (config.agent_dir / "constitution.md").write_text("   \n  \n")
    prompt = _system_prompt(config, state)
    assert "Constitution" not in prompt
    assert "my memory body" in prompt
