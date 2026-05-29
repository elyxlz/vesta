"""Tests for OpenRouter provider mode: config parsing, ZDR injection, and SDK option gating."""

import json

import core.models as vm
from core.client import build_client_options
from core.openrouter_proxy import inject_provider


def test_inject_provider_adds_zdr_to_json_body():
    body = json.dumps({"model": "anthropic/claude-sonnet-4-6", "messages": []}).encode()
    out = json.loads(inject_provider(body, zdr=True))
    assert out["provider"] == {"zdr": True, "data_collection": "deny"}


def test_inject_provider_noop_when_disabled():
    body = json.dumps({"model": "x"}).encode()
    assert inject_provider(body, zdr=False) == body


def test_inject_provider_passes_through_non_json():
    assert inject_provider(b"not json", zdr=True) == b"not json"
    assert inject_provider(b"", zdr=True) == b""


def test_inject_provider_merges_existing_provider():
    body = json.dumps({"provider": {"order": ["anthropic"]}}).encode()
    out = json.loads(inject_provider(body, zdr=True))
    assert out["provider"]["order"] == ["anthropic"]
    assert out["provider"]["zdr"] is True


def test_config_parses_provider_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_ZDR", "0")
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    assert config.agent_provider == "openrouter"
    assert config.openrouter_zdr is False


def test_config_defaults_to_claude(tmp_path):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    assert config.agent_provider == "claude"
    assert config.openrouter_zdr is True


def _config_with_memory(tmp_path, **overrides):
    config = vm.VestaConfig(agent_dir=tmp_path / "agent", **overrides)
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    (config.agent_dir / "MEMORY.md").write_text("test memory")
    return config


def test_build_client_options_keeps_anthropic_features_for_claude(tmp_path, state):
    config = _config_with_memory(tmp_path)
    options = build_client_options(config, state)
    assert options.betas == ["context-1m-2025-08-07"]
    assert options.thinking["type"] == "adaptive"


def test_build_client_options_drops_anthropic_features_for_openrouter(tmp_path, state):
    config = _config_with_memory(tmp_path, agent_provider="openrouter", agent_model="anthropic/claude-sonnet-4-6")
    options = build_client_options(config, state)
    assert options.betas == []
    assert options.thinking["type"] == "disabled"
    assert options.model == "anthropic/claude-sonnet-4-6"
