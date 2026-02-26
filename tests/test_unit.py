"""Unit tests for Vesta core modules.

These tests verify configuration, utilities, and core functionality.
"""

import asyncio
import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import vesta.models as vm
import vesta.utils as vu
from vesta.core.init import get_memory_path


def _make_config(tmp_path: Path) -> vm.VestaConfig:
    return vm.VestaConfig(state_dir=tmp_path)


# Config tests


def test_config_paths_under_state_dir(tmp_path):
    """All config paths should be under state_dir."""
    config = _make_config(tmp_path)
    assert config.notifications_dir.is_relative_to(tmp_path)
    assert config.data_dir.is_relative_to(tmp_path)
    assert config.logs_dir.is_relative_to(tmp_path)
    assert config.memory_dir.is_relative_to(tmp_path)
    assert config.skills_dir.is_relative_to(tmp_path)


def test_config_default_values():
    """Config should have sensible defaults."""
    config = vm.VestaConfig()
    assert config.notification_check_interval > 0
    assert config.response_timeout > 0


# Init module tests


def test_memory_paths(tmp_path):
    """Memory path functions should return correct paths."""
    config = _make_config(tmp_path)
    assert config.memory_dir == tmp_path / "memory"
    assert get_memory_path(config) == tmp_path / "memory" / "MEMORY.md"
    assert config.skills_dir == tmp_path / "memory" / "skills"


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


# Deployment validation tests


def test_install_root_exists():
    """Install root should exist and contain expected directories."""
    config = vm.VestaConfig()
    assert config.install_root.exists(), f"Install root does not exist: {config.install_root}"
    assert config.install_root.is_dir(), f"Install root is not a directory: {config.install_root}"


def test_clis_directory_exists():
    """CLIs directory should exist under install root."""
    config = vm.VestaConfig()
    clis_dir = config.install_root / "clis"
    assert clis_dir.exists(), f"CLIs directory does not exist: {clis_dir}"
    assert clis_dir.is_dir(), f"CLIs path is not a directory: {clis_dir}"


def test_whatsapp_cli_source_exists():
    """WhatsApp CLI source directory should exist with required files."""
    config = vm.VestaConfig()
    whatsapp_dir = config.install_root / "clis" / "whatsapp"
    assert whatsapp_dir.exists(), f"WhatsApp CLI dir does not exist: {whatsapp_dir}"
    assert (whatsapp_dir / "go.mod").exists(), f"go.mod missing in {whatsapp_dir}"
    assert (whatsapp_dir / "main.go").exists(), f"main.go missing in {whatsapp_dir}"


def test_python_clis_exist():
    """Python CLI directories should exist with pyproject.toml."""
    config = vm.VestaConfig()
    clis_dir = config.install_root / "clis"

    python_clis = ["microsoft", "reminder", "todo"]
    for cli_name in python_clis:
        cli_dir = clis_dir / cli_name
        assert cli_dir.exists(), f"CLI directory does not exist: {cli_dir}"
        assert (cli_dir / "pyproject.toml").exists(), f"pyproject.toml missing in {cli_dir}"


# Message processor tests


@pytest.mark.anyio
async def test_message_processor_resets_on_error(tmp_path):
    """Message processor should reset client on error and notify about what happened."""
    from vesta.core.loops import message_processor

    config = _make_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    call_count = 0
    session_count = 0
    processed_messages = []

    async def mock_process_message(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        processed_messages.append(msg)
        if call_count == 1:
            raise RuntimeError("Simulated SDK buffer overflow")
        return (["OK"], None)

    await queue.put(("first message - will fail", True))

    mock_client = MagicMock()

    async def mock_enter(self):
        nonlocal session_count
        session_count += 1
        return mock_client

    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def run_processor():
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

    assert call_count >= 1
    assert session_count >= 2, f"Expected at least 2 sessions (initial + reset), got {session_count}"
    assert state.session_id is None, "session_id should be cleared on error reset"
    assert any("Previous request failed" in msg for msg in processed_messages)


@pytest.mark.anyio
async def test_message_processor_restart_preserves_session(tmp_path):
    """Restart (via pending_context) should preserve session_id."""
    from vesta.core.loops import message_processor

    config = _make_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    call_count = 0
    session_count = 0
    processed_messages = []

    async def mock_process_message(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        processed_messages.append(msg)
        if call_count == 1:
            state.session_id = "test-session-123"
            state.pending_context = "[System: Vesta restarted.]"
        return (["OK"], None)

    await queue.put(("edit some config", True))

    mock_client = MagicMock()

    async def mock_enter(self):
        nonlocal session_count
        session_count += 1
        return mock_client

    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def run_processor():
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

    assert state.session_id == "test-session-123", "session_id should be preserved across restart"
    assert session_count >= 2, f"Expected at least 2 sessions (initial + restart), got {session_count}"
    assert any("restarted" in msg.lower() for msg in processed_messages)
