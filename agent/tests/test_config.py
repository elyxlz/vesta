"""Tests for VestaConfig and initialization."""

from core.helpers import get_memory_path


def test_config_paths_under_agent_dir(config, tmp_path):
    assert config.notifications_dir.is_relative_to(config.agent_dir)
    assert config.data_dir.is_relative_to(config.agent_dir)
    assert config.logs_dir.is_relative_to(config.agent_dir)
    assert config.skills_dir.is_relative_to(config.agent_dir)


def test_config_default_values():
    import core.models as vm

    config = vm.VestaConfig()
    assert config.monitor_tick_interval > 0
    assert config.response_timeout > 0


def test_memory_paths(config):
    assert get_memory_path(config) == config.agent_dir / "MEMORY.md"
    assert config.skills_dir == config.agent_dir / "skills"
