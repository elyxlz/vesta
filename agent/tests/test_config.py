"""Tests for VestaConfig and initialization."""

from core.init import get_memory_path


def test_config_paths_under_root(config, tmp_path):
    assert config.notifications_dir.is_relative_to(tmp_path)
    assert config.data_dir.is_relative_to(tmp_path)
    assert config.logs_dir.is_relative_to(tmp_path)
    assert config.skills_dir.is_relative_to(config.root)


def test_config_default_values():
    import core.models as vm

    config = vm.VestaConfig()
    assert config.monitor_tick_interval > 0
    assert config.response_timeout > 0


def test_memory_paths(config):
    assert get_memory_path(config) == config.agent_dir / "MEMORY.md"
    assert config.skills_dir == config.agent_dir / "skills"
