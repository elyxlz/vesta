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


def test_thinking_legacy_json_dict_coerces_with_defaults(monkeypatch):
    """Env files written before adaptive.display was required carry the JSON-dict form
    (e.g. THINKING='{"type":"adaptive"}'); it must coerce, not fail union validation."""
    from core.config import VestaConfig

    monkeypatch.setenv("THINKING", '{"type":"adaptive"}')
    assert VestaConfig().thinking == {"type": "adaptive", "display": "summarized"}
    monkeypatch.setenv("THINKING", '{"type":"enabled"}')
    assert VestaConfig().thinking == {"type": "enabled", "budget_tokens": 10000}
    monkeypatch.setenv("THINKING", '{"type":"disabled"}')
    assert VestaConfig().thinking == {"type": "disabled"}


def test_thinking_string_form_still_parses(monkeypatch):
    from core.config import VestaConfig

    monkeypatch.setenv("THINKING", "adaptive")
    assert VestaConfig().thinking == {"type": "adaptive", "display": "summarized"}
    monkeypatch.setenv("THINKING", "disabled")
    assert VestaConfig().thinking == {"type": "disabled"}
