"""Unit tests for Vesta core modules.

These tests verify configuration, utilities, and core functionality.
"""

import datetime as dt
from pathlib import Path

from pydantic import SecretStr

import vesta.models as vm
import vesta.utils as vu
from vesta.core.init import (
    get_memory_dir,
    get_memory_path,
    get_skills_dir,
    get_dreamer_memory_path,
    get_backups_dir,
)


def _make_config(tmp_path: Path) -> vm.VestaConfig:
    return vm.VestaConfig(state_dir=tmp_path, microsoft_mcp_client_id=SecretStr("test"))


# Config tests


def test_config_paths_under_state_dir(tmp_path):
    """All config paths should be under state_dir."""
    config = _make_config(tmp_path)
    assert config.notifications_dir.is_relative_to(tmp_path)
    assert config.data_dir.is_relative_to(tmp_path)
    assert config.logs_dir.is_relative_to(tmp_path)
    assert config.memory_dir.is_relative_to(tmp_path)
    assert config.skills_dir.is_relative_to(tmp_path)
    assert config.backups_dir.is_relative_to(tmp_path)


def test_config_onedrive_in_tmp():
    """OneDrive mount should be in /tmp."""
    config = vm.VestaConfig(microsoft_mcp_client_id=SecretStr("test"))
    assert str(config.onedrive_dir).startswith("/tmp")


def test_config_default_values():
    """Config should have sensible defaults."""
    config = vm.VestaConfig(microsoft_mcp_client_id=SecretStr("test"))
    assert config.notification_check_interval > 0
    assert config.response_timeout > 0
    assert config.shutdown_timeout > 0


# Init module tests


def test_memory_paths(tmp_path):
    """Memory path functions should return correct paths."""
    config = _make_config(tmp_path)
    assert get_memory_dir(config) == tmp_path / "memory"
    assert get_memory_path(config) == tmp_path / "memory" / "MEMORY.md"
    assert get_skills_dir(config) == tmp_path / "memory" / "skills"
    assert get_dreamer_memory_path(config) == tmp_path / "memory" / "DREAMER_MEMORY.md"
    assert get_backups_dir(config) == tmp_path / "backups"


# Utils tests


def test_format_tool_call_task():
    """Task tool calls should be formatted with agent type."""
    formatted, context = vu.format_tool_call(
        "Task",
        input_data={"subagent_type": "test-agent", "description": "do something"},
        sub_agent_context=None,
    )
    assert "[TASK]" in formatted
    assert "test-agent" in formatted
    assert context == "test-agent"


def test_format_tool_call_mcp():
    """MCP tool calls should show service and action."""
    formatted, context = vu.format_tool_call(
        "mcp__whatsapp__send_message",
        input_data={"to": "user", "message": "hello"},
        sub_agent_context=None,
    )
    assert "[TOOL]" in formatted
    assert "whatsapp" in formatted


def test_format_notification_batch_single():
    """Single notification should not have batch header."""
    notif = vm.Notification(
        timestamp=dt.datetime(2025, 1, 1, 0, 0, 0),
        source="test",
        type="message",
    )
    formatted = vu.format_notification_batch([notif])
    assert "[NOTIFICATIONS]" not in formatted


def test_format_notification_batch_multiple():
    """Multiple notifications should have batch header."""
    notifs = [
        vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 0), source="test", type="message"),
        vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 1), source="test", type="message"),
    ]
    formatted = vu.format_notification_batch(notifs)
    assert "[NOTIFICATIONS]" in formatted


def test_decide_notification_action():
    """Notification action should depend on processing state."""
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 0), source="test", type="message")

    # No notifications = skip
    assert vu.decide_notification_action([], is_processing=False, has_client=True) == "skip"

    # Processing with client = interrupt
    assert vu.decide_notification_action([notif], is_processing=True, has_client=True) == "interrupt"

    # Not processing = queue
    assert vu.decide_notification_action([notif], is_processing=False, has_client=True) == "queue"
