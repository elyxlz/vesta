"""Unit tests for Vesta core modules.

These tests verify configuration, utilities, and core functionality.
"""

import asyncio
import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

import vesta.models as vm
import vesta.utils as vu
from vesta.core.init import get_memory_path


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


def test_config_onedrive_under_state_dir():
    """OneDrive mount should be under state_dir."""
    config = vm.VestaConfig(microsoft_mcp_client_id=SecretStr("test"))
    assert config.onedrive_dir.is_relative_to(config.state_dir)


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
    assert config.memory_dir == tmp_path / "memory"
    assert get_memory_path(config) == tmp_path / "memory" / "MEMORY.md"
    assert config.skills_dir == tmp_path / "memory" / "skills"
    assert config.backups_dir == tmp_path / "backups"


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


# Deployment validation tests


def test_install_root_exists():
    """Install root should exist and contain expected directories."""
    config = vm.VestaConfig(microsoft_mcp_client_id=SecretStr("test"))
    assert config.install_root.exists(), f"Install root does not exist: {config.install_root}"
    assert config.install_root.is_dir(), f"Install root is not a directory: {config.install_root}"


def test_mcps_directory_exists():
    """MCPs directory should exist under install root."""
    config = vm.VestaConfig(microsoft_mcp_client_id=SecretStr("test"))
    mcps_dir = config.install_root / "mcps"
    assert mcps_dir.exists(), f"MCPs directory does not exist: {mcps_dir}"
    assert mcps_dir.is_dir(), f"MCPs path is not a directory: {mcps_dir}"


def test_whatsapp_mcp_source_exists():
    """WhatsApp MCP source directory should exist with required files."""
    config = vm.VestaConfig(microsoft_mcp_client_id=SecretStr("test"))
    whatsapp_dir = config.whatsapp_build_dir
    assert whatsapp_dir.exists(), f"WhatsApp MCP dir does not exist: {whatsapp_dir}"
    assert (whatsapp_dir / "go.mod").exists(), f"go.mod missing in {whatsapp_dir}"
    assert (whatsapp_dir / "main.go").exists(), f"main.go missing in {whatsapp_dir}"


def test_python_mcps_exist():
    """Python MCP directories should exist with pyproject.toml."""
    config = vm.VestaConfig(microsoft_mcp_client_id=SecretStr("test"))
    mcps_dir = config.install_root / "mcps"

    python_mcps = ["reminder-mcp", "task-mcp", "microsoft-mcp"]
    for mcp_name in python_mcps:
        mcp_dir = mcps_dir / mcp_name
        assert mcp_dir.exists(), f"MCP directory does not exist: {mcp_dir}"
        assert (mcp_dir / "pyproject.toml").exists(), f"pyproject.toml missing in {mcp_dir}"


# Message processor tests


@pytest.mark.anyio
async def test_message_processor_resets_and_notifies_on_error(tmp_path):
    """Message processor should reset client on error and notify about what happened."""
    from vesta.core.loops import message_processor

    config = _make_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    # Track how many times process_message is called and client sessions created
    call_count = 0
    session_count = 0
    processed_messages = []

    async def mock_process_message(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        processed_messages.append(msg)
        if call_count == 1:
            raise Exception("Simulated SDK buffer overflow")
        return (["OK"], None)

    # Queue a message that will fail
    await queue.put(("first message - will fail", True))

    # Mock the SDK client
    mock_client = MagicMock()

    async def mock_enter(self):
        nonlocal session_count
        session_count += 1
        return mock_client

    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def run_processor():
        # Wait for error to be processed and client to restart
        await asyncio.sleep(0.15)
        assert state.shutdown_event is not None
        state.shutdown_event.set()

    with (
        patch("vesta.core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("vesta.core.loops.process_message", side_effect=mock_process_message),
        patch("vesta.core.loops.build_client_options", return_value=MagicMock()),
    ):
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            run_processor(),
        )

    # First message should have been attempted
    assert call_count >= 1, f"Expected at least 1 call, got {call_count}"
    # Client should have been reset (new session created)
    assert session_count >= 2, f"Expected at least 2 sessions (initial + reset), got {session_count}"
    # Error context should have been queued and processed
    assert any("Previous request failed" in msg for msg in processed_messages), (
        f"Expected error context in processed messages, got: {processed_messages}"
    )
