"""Unit tests for Vesta agents module.

These tests verify the consistency of agent configuration and memory templates.
"""

from pathlib import Path


import vesta.models as vm
from vesta.registry import (
    build_all_agents,
    get_active_agents,
    get_memory_templates,
    ALL_AGENTS,
    MCP_REGISTRY,
)


def _make_config(tmp_path: Path) -> vm.VestaSettings:
    return vm.VestaSettings(state_dir=tmp_path, microsoft_mcp_client_id="test")


# Agent consistency tests - prevent drift between registry and templates


def test_agent_names_derived_from_configs(tmp_path):
    """config.active_agents must return names from ALL_AGENTS."""
    config = _make_config(tmp_path)
    for name in config.active_agents:
        assert name in ALL_AGENTS, f"Active agent {name} not in ALL_AGENTS"


def test_all_agents_have_memory_templates(tmp_path):
    """Every active agent must have a corresponding memory template."""
    config = _make_config(tmp_path)
    templates = get_memory_templates(config)
    for name in config.active_agents:
        assert name in templates, f"Missing template for {name}"


def test_no_orphan_templates(tmp_path):
    """All templates (except 'main') must correspond to an active agent."""
    config = _make_config(tmp_path)
    agent_names_set = set(config.active_agents) | {"main"}
    templates = get_memory_templates(config)
    assert set(templates.keys()) == agent_names_set


def test_agent_configs_are_valid():
    """Each agent definition must have required fields with valid values."""
    for name, agent in ALL_AGENTS.items():
        assert agent.name == name
        assert agent.description
        assert agent.mcp in MCP_REGISTRY  # MCP must exist in registry


def test_mcp_definitions_have_tools():
    """Each MCP definition must have tool suffixes."""
    for name, mcp in MCP_REGISTRY.items():
        assert mcp.name == name
        assert len(mcp.tool_suffixes) > 0
        assert all(mcp.tool_ids)  # tool_ids property should work


# Build agents tests


def test_builds_all_configured_agents(tmp_path):
    """build_all_agents returns one agent per active agent."""
    config = _make_config(tmp_path)
    agents = build_all_agents(config)
    assert set(agents.keys()) == set(config.active_agents)


def test_agents_have_prompts_and_tools(tmp_path):
    """Each built agent has a prompt (from memory) and tools."""
    config = _make_config(tmp_path)
    agents = build_all_agents(config)
    for name, agent in agents.items():
        assert agent.prompt, f"{name} missing prompt"
        assert agent.tools, f"{name} missing tools"
