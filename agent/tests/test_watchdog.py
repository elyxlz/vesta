"""Tests for SDK activity watchdog, tool duration tracking, and hang diagnostics."""

import asyncio
import time
import typing as tp
from unittest.mock import AsyncMock, MagicMock

import pytest
import core.models as vm
from core.client import (
    _check_sdk_subprocess_alive,
    _format_hang_diagnostics,
    _sdk_watchdog,
    converse,
)


# --- ActiveTool and State activity tracking ---


def test_touch_activity_updates_timestamp_and_label():
    state = vm.State()
    before = state.last_sdk_activity
    time.sleep(0.01)
    state.touch_activity("tool_start:Read")
    assert state.last_sdk_activity > before
    assert state.last_sdk_activity_label == "tool_start:Read"


def test_sdk_idle_seconds_increases_over_time():
    state = vm.State()
    state.last_sdk_activity = time.monotonic() - 42.0
    idle = state.sdk_idle_seconds()
    assert 41.5 < idle < 43.0


def test_longest_running_tool_returns_oldest():
    state = vm.State()
    now = time.monotonic()
    state.active_tools["a"] = vm.ActiveTool(name="Bash", summary="ls", started_at=now - 10)
    state.active_tools["b"] = vm.ActiveTool(name="Read", summary="/tmp/x", started_at=now - 30)
    state.active_tools["c"] = vm.ActiveTool(name="Grep", summary="foo", started_at=now - 5)
    longest = state.longest_running_tool()
    assert longest is not None
    assert longest.name == "Read"


def test_longest_running_tool_returns_none_when_empty():
    state = vm.State()
    assert state.longest_running_tool() is None


# --- _format_hang_diagnostics ---


def test_format_hang_diagnostics_minimal():
    state = vm.State()
    state.touch_activity("query_sent")
    diag = _format_hang_diagnostics(state)
    assert "idle=" in diag
    assert "last_activity=query_sent" in diag
    assert "longest_tool" not in diag
    assert "active_tools" not in diag


def test_format_hang_diagnostics_with_active_tools():
    state = vm.State()
    state.touch_activity("tool_start:Agent")
    now = time.monotonic()
    state.active_tools["t1"] = vm.ActiveTool(name="Agent", summary="research", started_at=now - 120, is_subagent=True)
    state.active_tools["t2"] = vm.ActiveTool(name="Read", summary="/tmp/x", started_at=now - 5)
    diag = _format_hang_diagnostics(state)
    assert "longest_tool=Agent" in diag
    assert "sub=True" in diag
    assert "active_tools=2" in diag


def test_format_hang_diagnostics_includes_stderr_tail():
    state = vm.State()
    for i in range(10):
        state.stderr_buffer.append(f"line {i}")
    diag = _format_hang_diagnostics(state)
    assert "stderr_tail=" in diag
    assert "line 4" not in diag  # Only last 5
    assert "line 9" in diag


# --- _check_sdk_subprocess_alive ---


def test_subprocess_alive_returns_true_when_running():
    state = vm.State()
    mock_client = MagicMock()
    mock_transport = MagicMock()
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_transport._process = mock_process
    mock_client._transport = mock_transport
    state.client = mock_client
    assert _check_sdk_subprocess_alive(state) is True


def test_subprocess_alive_returns_false_when_exited():
    state = vm.State()
    mock_client = MagicMock()
    mock_transport = MagicMock()
    mock_process = MagicMock()
    mock_process.returncode = 1
    mock_transport._process = mock_process
    mock_client._transport = mock_transport
    state.client = mock_client
    assert _check_sdk_subprocess_alive(state) is False


def test_subprocess_alive_returns_none_when_no_client():
    state = vm.State()
    state.client = None
    assert _check_sdk_subprocess_alive(state) is None


def test_subprocess_alive_returns_none_on_missing_attrs():
    state = vm.State()
    mock_client = MagicMock(spec=[])  # No attributes at all
    state.client = mock_client
    assert _check_sdk_subprocess_alive(state) is None


# --- _sdk_watchdog ---


@pytest.mark.anyio
async def test_watchdog_warns_at_thresholds():
    """Patch the sleep to 0 so the watchdog ticks immediately."""
    from unittest.mock import patch as _patch

    import core.client as client_mod

    state = vm.State()
    state.last_sdk_activity = time.monotonic() - 65  # Idle for 65s
    stop = asyncio.Event()
    warnings: list[str] = []

    original_warning = client_mod.logger.warning

    def capture_warning(msg):
        warnings.append(str(msg))

    client_mod.logger.warning = capture_warning  # ty: ignore[invalid-assignment]

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        return await original_wait_for(coro, timeout=0.01)

    try:

        async def stop_after_tick():
            await asyncio.sleep(0.05)
            stop.set()

        with _patch("core.client.asyncio.wait_for", fast_wait_for):
            await asyncio.gather(_sdk_watchdog(state, stop=stop), stop_after_tick())
    finally:
        client_mod.logger.warning = original_warning

    assert any("SDK silent for 60s" in w for w in warnings), f"Expected 60s warning, got: {warnings}"


@pytest.mark.anyio
async def test_watchdog_resets_after_activity_resumes():
    from unittest.mock import patch as _patch

    import core.client as client_mod

    state = vm.State()
    state.last_sdk_activity = time.monotonic() - 65  # Idle
    stop = asyncio.Event()
    warnings: list[str] = []

    original_warning = client_mod.logger.warning

    def capture_warning(msg):
        warnings.append(str(msg))

    client_mod.logger.warning = capture_warning  # ty: ignore[invalid-assignment]

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        return await original_wait_for(coro, timeout=0.01)

    try:

        async def resume_then_idle_again():
            await asyncio.sleep(0.05)
            state.touch_activity("sdk_message")
            await asyncio.sleep(0.05)
            state.last_sdk_activity = time.monotonic() - 65
            await asyncio.sleep(0.05)
            stop.set()

        with _patch("core.client.asyncio.wait_for", fast_wait_for):
            await asyncio.gather(_sdk_watchdog(state, stop=stop), resume_then_idle_again())
    finally:
        client_mod.logger.warning = original_warning

    sixty_warnings = [w for w in warnings if "SDK silent for 60s" in w]
    assert len(sixty_warnings) >= 2, f"Expected 60s warning to fire again after reset, got {len(sixty_warnings)}: {warnings}"


@pytest.mark.anyio
async def test_watchdog_stops_cleanly():
    state = vm.State()
    stop = asyncio.Event()
    stop.set()  # Stop immediately
    await _sdk_watchdog(state, stop=stop)  # Should not hang


# --- Tool duration tracking via hooks ---


@pytest.mark.anyio
async def test_tool_hooks_track_active_tools():
    """PreToolUse adds to active_tools, PostToolUse removes and logs duration."""
    from claude_agent_sdk import HookContext
    from claude_agent_sdk.types import PostToolUseHookInput, PreToolUseHookInput

    import core.client as client_mod

    state = vm.State()
    hooks = client_mod._make_hooks(state)

    pre_hook = hooks["PreToolUse"][0].hooks[0]
    post_hook = hooks["PostToolUse"][0].hooks[0]

    pre_input = tp.cast(PreToolUseHookInput, {"tool_name": "Read", "tool_input": {"file_path": "/tmp/test.py"}})
    ctx = tp.cast(HookContext, MagicMock())

    await pre_hook(pre_input, "tool-123", ctx)
    assert "tool-123" in state.active_tools
    assert state.active_tools["tool-123"].name == "Read"
    assert state.last_sdk_activity_label == "tool_start:Read"

    post_input = tp.cast(PostToolUseHookInput, {"tool_name": "Read", "tool_input": {"file_path": "/tmp/test.py"}})
    await post_hook(post_input, "tool-123", ctx)
    assert "tool-123" not in state.active_tools
    assert state.last_sdk_activity_label == "tool_end:Read"


@pytest.mark.anyio
async def test_tool_failure_hook_cleans_up():
    from claude_agent_sdk import HookContext
    from claude_agent_sdk.types import PostToolUseFailureHookInput, PreToolUseHookInput

    import core.client as client_mod

    state = vm.State()
    hooks = client_mod._make_hooks(state)

    pre_hook = hooks["PreToolUse"][0].hooks[0]
    fail_hook = hooks["PostToolUseFailure"][0].hooks[0]
    ctx = tp.cast(HookContext, MagicMock())

    pre_input = tp.cast(PreToolUseHookInput, {"tool_name": "Bash", "tool_input": {"command": "exit 1"}})
    await pre_hook(pre_input, "tool-456", ctx)
    assert "tool-456" in state.active_tools

    fail_input = tp.cast(PostToolUseFailureHookInput, {"tool_name": "Bash", "error": "command failed"})
    await fail_hook(fail_input, "tool-456", ctx)
    assert "tool-456" not in state.active_tools
    assert state.last_sdk_activity_label == "tool_fail:Bash"


# --- converse() watchdog integration ---


@pytest.mark.anyio
async def test_converse_touches_activity_on_messages():
    """converse updates last_sdk_activity when SDK messages arrive."""
    state = vm.State()
    config = vm.VestaConfig(interrupt_timeout=0.5)

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    async def three_messages():
        for _ in range(3):
            msg = MagicMock()
            msg.content = []
            yield msg

    mock_client.receive_response = MagicMock(return_value=three_messages())

    await converse("test", state=state, config=config, show_output=False)

    assert state.last_sdk_activity_label == "sdk_message"


@pytest.mark.anyio
async def test_converse_clears_active_tools_on_start():
    """converse clears stale active_tools from prior calls."""
    state = vm.State()
    config = vm.VestaConfig(interrupt_timeout=0.5)
    state.active_tools["stale"] = vm.ActiveTool(name="Old", summary="leftover", started_at=0)

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    async def empty_response():
        return
        yield  # Make it an async generator

    mock_client.receive_response = MagicMock(return_value=empty_response())

    await converse("test", state=state, config=config, show_output=False)

    assert "stale" not in state.active_tools
