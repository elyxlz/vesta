"""Unit tests for Vesta core modules.

These tests verify configuration, utilities, and core functionality.
"""

import asyncio
import datetime as dt
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import vesta.models as vm
from vesta.core.client import _format_tool_call
from vesta.core.init import get_memory_path
from vesta.core.notifications import format_notification_batch


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
    formatted, context = _format_tool_call(
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
    formatted = format_notification_batch([notif])
    assert "[NOTIFICATIONS]" not in formatted


def test_format_notification_batch_multiple():
    """Multiple notifications should have batch header."""
    notifs = [
        vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 0), source="test", type="message"),
        vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 1), source="test", type="message"),
    ]
    formatted = format_notification_batch(notifs)
    assert "[NOTIFICATIONS]" in formatted


# Deployment validation tests


def test_install_root_exists():
    """Install root should exist and contain expected directories."""
    config = vm.VestaConfig()
    assert config.install_root.exists(), f"Install root does not exist: {config.install_root}"
    assert config.install_root.is_dir(), f"Install root is not a directory: {config.install_root}"


def test_tools_directory_exists():
    """Tools directory should exist under install root."""
    config = vm.VestaConfig()
    tools_dir = config.install_root / "tools"
    assert tools_dir.exists(), f"Tools directory does not exist: {tools_dir}"
    assert tools_dir.is_dir(), f"Tools path is not a directory: {tools_dir}"


def test_whatsapp_tool_source_exists():
    """WhatsApp tool source directory should exist with required files."""
    config = vm.VestaConfig()
    whatsapp_dir = config.install_root / "tools" / "whatsapp"
    assert whatsapp_dir.exists(), f"WhatsApp tool dir does not exist: {whatsapp_dir}"
    assert (whatsapp_dir / "go.mod").exists(), f"go.mod missing in {whatsapp_dir}"
    assert (whatsapp_dir / "main.go").exists(), f"main.go missing in {whatsapp_dir}"


def test_python_tools_exist():
    """Python tool directories should exist with pyproject.toml."""
    config = vm.VestaConfig()
    tools_dir = config.install_root / "tools"

    python_tools = ["microsoft", "reminder", "todo"]
    for tool_name in python_tools:
        tool_dir = tools_dir / tool_name
        assert tool_dir.exists(), f"Tool directory does not exist: {tool_dir}"
        assert (tool_dir / "pyproject.toml").exists(), f"pyproject.toml missing in {tool_dir}"


def test_skill_templates_discovered():
    """All skill templates should be discovered from the templates directory."""
    from vesta.core.init import _discover_skill_templates

    templates = _discover_skill_templates()
    expected = {"browser", "google", "keeper", "microsoft", "onedrive", "reminders", "report-writer", "todos", "what-day", "whatsapp", "whisper", "zoom"}
    assert set(templates.keys()) == expected

    for name, path in templates.items():
        assert (path / "SKILL.md").exists(), f"SKILL.md missing for {name}"


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
        return (["OK"], state)

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
        return (["OK"], state)

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


@pytest.mark.anyio
async def test_dreamer_queues_prompt_and_archives(tmp_path):
    """Dreamer should archive conversation, queue prompt, set dreamer_active, and update last_dreamer_run."""
    from vesta.core.loops import process_nightly_memory

    state = vm.State()
    state.last_dreamer_run = None
    queue: asyncio.Queue = asyncio.Queue()

    dreamer_hour = 4
    config = vm.VestaConfig(state_dir=tmp_path, nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    with (
        patch("vesta.core.loops.vfx.get_current_time", return_value=fake_now),
        patch("vesta.core.loops.archive_conversation") as mock_archive,
        patch("vesta.core.loops.build_dreamer_prompt", return_value="dreamer prompt"),
    ):
        await process_nightly_memory(queue, state=state, config=config)

    assert not queue.empty(), "Dreamer prompt should be queued"
    msg, is_user = await queue.get()
    assert msg == "dreamer prompt"
    assert is_user is False
    assert state.last_dreamer_run == fake_now
    assert state.dreamer_active is True
    mock_archive.assert_called_once()


@pytest.mark.anyio
async def test_dreamer_skips_when_already_run_today(tmp_path):
    """Dreamer should not run twice on the same day."""
    from vesta.core.loops import process_nightly_memory

    dreamer_hour = 4
    config = vm.VestaConfig(state_dir=tmp_path, nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    state = vm.State()
    state.last_dreamer_run = fake_now
    queue: asyncio.Queue = asyncio.Queue()

    with (
        patch("vesta.core.loops.vfx.get_current_time", return_value=fake_now),
        patch("vesta.core.loops.archive_conversation") as mock_archive,
        patch("vesta.core.loops.build_dreamer_prompt", return_value="dreamer prompt"),
    ):
        await process_nightly_memory(queue, state=state, config=config)

    assert queue.empty(), "Dreamer should not run again on the same day"
    assert state.dreamer_active is False
    mock_archive.assert_not_called()


# Nightly restart tests


def test_nightly_restart_clears_session_and_includes_summary(tmp_path):
    """After dreamer completes, nightly restart should clear session_id and include dreamer summary."""
    from vesta.core.loops import _trigger_nightly_restart

    config = vm.VestaConfig(state_dir=tmp_path)
    state = vm.State()
    state.session_id = "old-session-abc"

    config.dreamer_dir.mkdir(parents=True, exist_ok=True)
    summary_path = config.dreamer_dir / "2025-06-15.md"
    summary_path.write_text("Updated MEMORY.md, pruned stale entries.")

    fake_now = dt.datetime(2025, 6, 15, 4, 5, 0)
    with patch("vesta.core.loops.vfx.get_current_time", return_value=fake_now):
        _trigger_nightly_restart(state=state, config=config)

    assert state.session_id is None, "session_id should be cleared for fresh start"
    assert state.pending_context is not None
    assert "Good morning" in state.pending_context
    assert "Updated MEMORY.md" in state.pending_context


def test_nightly_restart_includes_returning_start_prompt(tmp_path):
    """Nightly restart should include the returning_start prompt."""
    from vesta.core.loops import _trigger_nightly_restart

    config = vm.VestaConfig(state_dir=tmp_path)
    state = vm.State()

    config.prompts_dir.mkdir(parents=True, exist_ok=True)
    (config.prompts_dir / "returning_start.md").write_text("Say good morning via WhatsApp.")

    fake_now = dt.datetime(2025, 6, 15, 4, 5, 0)
    with patch("vesta.core.loops.vfx.get_current_time", return_value=fake_now):
        _trigger_nightly_restart(state=state, config=config)

    assert state.pending_context is not None
    assert "Say good morning via WhatsApp" in state.pending_context


def test_nightly_restart_works_without_summary_file(tmp_path):
    """Nightly restart should work even if no dreamer summary was written."""
    from vesta.core.loops import _trigger_nightly_restart

    config = vm.VestaConfig(state_dir=tmp_path)
    state = vm.State()
    state.session_id = "some-session"

    fake_now = dt.datetime(2025, 6, 15, 4, 5, 0)
    with patch("vesta.core.loops.vfx.get_current_time", return_value=fake_now):
        _trigger_nightly_restart(state=state, config=config)

    assert state.session_id is None
    assert state.pending_context is not None
    assert "Good morning" in state.pending_context
    assert "Dreamer summary" not in state.pending_context


@pytest.mark.anyio
async def test_dreamer_triggers_automatic_restart(tmp_path):
    """Message processor should automatically restart after dreamer completes."""
    from vesta.core.loops import message_processor

    config = vm.VestaConfig(state_dir=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.session_id = "pre-dreamer-session"
    queue: asyncio.Queue = asyncio.Queue()

    call_count = 0
    session_count = 0
    processed_messages = []

    async def mock_process_message(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        processed_messages.append(msg)
        return (["OK"], state)

    state.dreamer_active = True
    await queue.put(("dreamer prompt content", False))

    mock_client = MagicMock()

    async def mock_enter(self):
        nonlocal session_count
        session_count += 1
        return mock_client

    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    fake_now = dt.datetime(2025, 6, 15, 4, 5, 0)

    async def run_processor():
        await asyncio.sleep(0.15)
        assert state.shutdown_event is not None
        state.shutdown_event.set()

    with (
        patch("vesta.core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("vesta.core.loops.process_message", side_effect=mock_process_message),
        patch("vesta.core.loops.build_client_options", return_value=MagicMock()),
        patch("vesta.core.loops.vfx.get_current_time", return_value=fake_now),
    ):
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            run_processor(),
        )

    assert state.session_id is None, "session_id should be cleared after nightly restart"
    assert state.dreamer_active is False
    assert session_count >= 2, f"Expected at least 2 sessions (pre-dreamer + post-restart), got {session_count}"
    assert any("Good morning" in msg for msg in processed_messages)


# Response timeout test


@pytest.mark.anyio
async def test_response_timeout_triggers_session_reset(tmp_path):
    """Response timeout (via pending_context) should trigger a new session while preserving session_id."""
    from vesta.core.loops import message_processor

    config = vm.VestaConfig(state_dir=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.session_id = "timeout-session"
    queue: asyncio.Queue = asyncio.Queue()

    call_count = 0
    session_count = 0
    processed_messages = []

    async def mock_process_message(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        processed_messages.append(msg)
        if call_count == 1:
            state.pending_context = "[System: Response timed out. Session was reset to recover.]"
        return (["OK"], state)

    await queue.put(("slow request", True))

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

    assert session_count >= 2, f"Expected at least 2 sessions (initial + after timeout), got {session_count}"
    assert state.session_id == "timeout-session", "session_id should be preserved after timeout"
    assert any("timed out" in msg.lower() for msg in processed_messages)
