"""The personality voice (shared SKILL.md + the active preset) is the single source of truth
for how the agent sounds. It lives in the agent-editable personality skill, but core loads it
into the system prompt on every boot so the voice is as unskippable as MEMORY.md. The active
preset is selected by the AGENT_PERSONALITY env var (vestad writes it at agent creation).
These tests cover the prompt-assembly side."""

import core.models as vm
from core.client import build_client_options


def _config(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("my memory body")
    return config


def _write_voice(config, *, shared: str, presets: dict[str, str]):
    personality = config.skills_dir / "personality"
    (personality / "presets").mkdir(parents=True, exist_ok=True)
    (personality / "SKILL.md").write_text(shared)
    for name, body in presets.items():
        (personality / "presets" / f"{name}.md").write_text(body)


def _system_prompt(config, state) -> str:
    prompt = build_client_options(config, state).system_prompt
    assert isinstance(prompt, str)
    return prompt


def test_shared_voice_and_default_active_preset_are_loaded(tmp_path, state):
    # conftest sets AGENT_PERSONALITY=dry for the suite.
    config = _config(tmp_path)
    assert config.agent_personality == "dry"
    _write_voice(config, shared="shared voice rules", presets={"dry": "dry preset voice", "extra": "extra preset voice"})
    prompt = _system_prompt(config, state)
    assert "shared voice rules" in prompt
    assert "dry preset voice" in prompt
    assert "extra preset voice" not in prompt
    assert "my memory body" in prompt


def test_active_preset_is_selected_from_the_env(tmp_path, state, monkeypatch):
    monkeypatch.setenv("AGENT_PERSONALITY", "extra")
    config = _config(tmp_path)
    _write_voice(config, shared="shared voice rules", presets={"dry": "dry preset voice", "extra": "extra preset voice"})
    prompt = _system_prompt(config, state)
    assert "extra preset voice" in prompt
    assert "dry preset voice" not in prompt


def test_legacy_seed_personality_env_name_still_selects_the_preset(tmp_path, state, monkeypatch):
    monkeypatch.delenv("AGENT_PERSONALITY", raising=False)
    monkeypatch.setenv("AGENT_SEED_PERSONALITY", "extra")
    config = _config(tmp_path)
    assert config.agent_personality == "extra"
    _write_voice(config, shared="shared voice rules", presets={"extra": "extra preset voice"})
    prompt = _system_prompt(config, state)
    assert "extra preset voice" in prompt


def test_missing_personality_skill_leaves_prompt_unchanged(tmp_path, state):
    config = _config(tmp_path)
    prompt = _system_prompt(config, state)
    assert "Active voice" not in prompt
    assert "my memory body" in prompt


def test_missing_preset_still_loads_shared_voice(tmp_path, state, monkeypatch):
    monkeypatch.setenv("AGENT_PERSONALITY", "nonexistent")
    config = _config(tmp_path)
    _write_voice(config, shared="shared voice rules", presets={"dry": "dry preset voice"})
    prompt = _system_prompt(config, state)
    assert "shared voice rules" in prompt
    assert "dry preset voice" not in prompt
