"""Unit tests for Vesta agents module.

These tests verify the consistency of agent configuration and memory templates.
"""

from pathlib import Path


import vesta.models as vm
from vesta.agents import AGENT_NAMES, AGENT_CONFIGS, build_all_agents
from vesta.agents.templates import MEMORY_TEMPLATES


def _make_config(tmp_path: Path) -> vm.VestaSettings:
    return vm.VestaSettings(state_dir=tmp_path, microsoft_mcp_client_id="test")


# Agent consistency tests - prevent drift between configs and templates


def test_agent_names_derived_from_configs():
    """AGENT_NAMES must be derived from AGENT_CONFIGS (single source of truth)."""
    assert AGENT_NAMES == [c.name for c in AGENT_CONFIGS]


def test_all_agents_have_memory_templates():
    """Every agent in AGENT_CONFIGS must have a corresponding memory template."""
    for config in AGENT_CONFIGS:
        assert config.name in MEMORY_TEMPLATES, f"Missing template for {config.name}"


def test_no_orphan_templates():
    """All templates (except 'main') must correspond to an agent."""
    agent_names_set = set(AGENT_NAMES) | {"main"}
    assert set(MEMORY_TEMPLATES.keys()) == agent_names_set


def test_agent_configs_are_valid():
    """Each agent config must have required fields with valid values."""
    for config in AGENT_CONFIGS:
        assert config.name
        assert config.description
        assert len(config.tools) > 0
        assert all(t.startswith("mcp__") for t in config.tools)


# Build agents tests


def test_builds_all_configured_agents(tmp_path):
    """build_all_agents returns one agent per config."""
    config = _make_config(tmp_path)
    agents = build_all_agents(config)
    assert set(agents.keys()) == set(AGENT_NAMES)


def test_agents_have_prompts_and_tools(tmp_path):
    """Each built agent has a prompt (from memory) and tools."""
    config = _make_config(tmp_path)
    agents = build_all_agents(config)
    for name, agent in agents.items():
        assert agent.prompt, f"{name} missing prompt"
        assert agent.tools, f"{name} missing tools"
