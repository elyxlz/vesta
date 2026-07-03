"""Tests for SDK activity watchdog, tool duration tracking, and hang diagnostics."""

import asyncio
import contextlib
import time
import typing as tp
from unittest.mock import AsyncMock, MagicMock

import pytest
import core.models as vm
from core.client import converse
from wait_util import wait_for_condition
from core.diagnostics import (
    format_hang_diagnostics,
    longest_running_tool,
    note_stream_silence,
    sdk_idle_seconds,
    touch_activity,
)


@pytest.fixture
def captured_warnings(monkeypatch):
    """Capture diagnostics warnings; the watchdog routes suspicious silence through logger.warning."""
    import core.diagnostics as diagnostics_mod

    warnings: list[str] = []
    monkeypatch.setattr(diagnostics_mod.logger, "warning", lambda msg: warnings.append(str(msg)))
    return warnings


@pytest.fixture
def captured_notes(monkeypatch):
    """Capture the INFO-band liveness notes note_stream_silence logs via logger.client."""
    import core.diagnostics as diagnostics_mod

    notes: list[str] = []
    monkeypatch.setattr(diagnostics_mod.logger, "client", lambda msg: notes.append(str(msg)))
    return notes


# --- ActiveTool and State activity tracking ---


def test_touch_activity_updates_timestamp_and_label():
    state = vm.State()
    before = state.last_sdk_activity
    time.sleep(0.01)
    touch_activity(state, "tool_start:Read")
    assert state.last_sdk_activity > before
    assert state.last_sdk_activity_label == "tool_start:Read"


def test_sdk_idle_seconds_increases_over_time():
    state = vm.State()
    state.last_sdk_activity = time.monotonic() - 42.0
    idle = sdk_idle_seconds(state)
    assert 41.5 < idle < 43.0


def test_longest_running_tool_returns_oldest():
    state = vm.State()
    now = time.monotonic()
    state.active_tools["a"] = vm.ActiveTool(name="Bash", summary="ls", started_at=now - 10)
    state.active_tools["b"] = vm.ActiveTool(name="Read", summary="/tmp/x", started_at=now - 30)
    state.active_tools["c"] = vm.ActiveTool(name="Grep", summary="foo", started_at=now - 5)
    longest = longest_running_tool(state)
    assert longest is not None
    assert longest.name == "Read"


def test_longest_running_tool_returns_none_when_empty():
    state = vm.State()
    assert longest_running_tool(state) is None


# --- format_hang_diagnostics ---


def test_format_hang_diagnostics_minimal():
    state = vm.State()
    touch_activity(state, "query_sent")
    diag = format_hang_diagnostics(state)
    assert "idle=" in diag
    assert "last_activity=query_sent" in diag
    assert "longest_tool" not in diag
    assert "active_tools" not in diag


def test_format_hang_diagnostics_with_active_tools():
    state = vm.State()
    touch_activity(state, "tool_start:Agent")
    now = time.monotonic()
    state.active_tools["t1"] = vm.ActiveTool(name="Agent", summary="research", started_at=now - 120, is_subagent=True)
    state.active_tools["t2"] = vm.ActiveTool(name="Read", summary="/tmp/x", started_at=now - 5)
    diag = format_hang_diagnostics(state)
    assert "longest_tool=Agent" in diag
    assert "sub=True" in diag
    assert "active_tools=2" in diag


def test_format_hang_diagnostics_includes_stderr_tail():
    state = vm.State()
    for i in range(10):
        state.stderr_buffer.append(f"line {i}")
    diag = format_hang_diagnostics(state)
    assert "stderr_tail=" in diag
    assert "line 4" not in diag  # Only last 5
    assert "line 9" in diag


# --- note_stream_silence ---


def _quiet_state(idle_s: float) -> vm.State:
    state = vm.State()
    state.last_sdk_activity = time.monotonic() - idle_s
    return state


def test_silence_notes_once_per_threshold(captured_notes):
    state = _quiet_state(65)
    noted: set[int] = set()

    note_stream_silence(state, noted_at=noted)
    note_stream_silence(state, noted_at=noted)

    assert len([n for n in captured_notes if "Model quiet for 60s" in n]) == 1, f"one note per crossing, got: {captured_notes}"
    assert noted == {60}


def test_silence_notes_each_threshold_as_idle_grows(captured_notes):
    state = _quiet_state(65)
    noted: set[int] = set()

    note_stream_silence(state, noted_at=noted)
    state.last_sdk_activity = time.monotonic() - 125
    note_stream_silence(state, noted_at=noted)

    assert [n for n in captured_notes if "Model quiet" in n] == [
        next(n for n in captured_notes if "60s" in n),
        next(n for n in captured_notes if "120s" in n),
    ], f"expected a 60s then a 120s note, got: {captured_notes}"


def test_silence_resets_when_stream_talks_again(captured_notes):
    state = _quiet_state(65)
    noted: set[int] = set()

    note_stream_silence(state, noted_at=noted)
    touch_activity(state, "sdk_message")
    note_stream_silence(state, noted_at=noted)  # fresh activity clears the noted set
    assert noted == set()

    state.last_sdk_activity = time.monotonic() - 65
    note_stream_silence(state, noted_at=noted)

    assert len([n for n in captured_notes if "Model quiet for 60s" in n]) == 2, f"expected a re-note after reset, got: {captured_notes}"


def test_silence_escalates_to_warning_and_event_past_escalation(captured_warnings, captured_notes, tmp_path):
    state = _quiet_state(305)
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    noted: set[int] = set()

    note_stream_silence(state, noted_at=noted)
    note_stream_silence(state, noted_at=noted)

    warnings_300 = [w for w in captured_warnings if "Model quiet for 300s" in w]
    assert len(warnings_300) == 1, f"expected exactly one 300s warning, got: {captured_warnings}"
    events = []
    while not queue.empty():
        event = queue.get_nowait()
        if event["type"] == "error" and "Model quiet" in event["text"]:
            events.append(event)
    assert len(events) == 1, f"expected exactly one error event, got: {events}"
    # The earlier thresholds stay calm INFO notes, not warnings.
    assert len([n for n in captured_notes if "Model quiet" in n]) == 2, f"60s+120s notes expected, got: {captured_notes}"
    state.event_bus.close()


def test_silence_stays_debug_while_tool_runs(captured_warnings, captured_notes, tmp_path):
    """A running tool explains the quiet (a long build, a sleep): no notes, no warnings, no events."""
    state = _quiet_state(305)
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    state.active_tools["tool-1"] = vm.ActiveTool(name="Bash", summary="sleep 180", started_at=time.monotonic() - 305)
    noted: set[int] = set()

    note_stream_silence(state, noted_at=noted)

    assert [n for n in captured_notes if "Model quiet" in n] == [], f"expected no notes mid-tool, got: {captured_notes}"
    assert [w for w in captured_warnings if "Model quiet" in w] == [], f"expected no warnings mid-tool, got: {captured_warnings}"
    assert queue.empty(), "expected no error events mid-tool"
    state.event_bus.close()


@pytest.mark.anyio
async def test_converse_notes_silence_while_waiting(captured_notes, monkeypatch):
    """The wait loop itself emits the liveness note during a long quiet stretch: a silent model
    reads as 'still thinking' in the log before the turn completes."""
    import core.client as client_mod
    import core.diagnostics as diagnostics_mod
    from claude_agent_sdk import ResultMessage
    from core.client import consume_stream

    monkeypatch.setattr(client_mod, "_SILENCE_POLL_S", 0.02)
    monkeypatch.setattr(diagnostics_mod, "_SILENCE_THRESHOLDS_S", (0,))

    state = vm.State()
    config = vm.VestaConfig(interrupt_timeout=0.5)
    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    q: asyncio.Queue = asyncio.Queue()

    async def stream():
        while True:
            yield await q.get()

    mock_client.receive_messages = MagicMock(side_effect=lambda: stream())
    consumer = asyncio.create_task(consume_stream(state=state, config=config))

    async def end_turn_after_quiet():
        await wait_for_condition(lambda: any("Model quiet" in n for n in captured_notes), message="no liveness note during silence")
        result = MagicMock(spec=ResultMessage)
        result.content = []
        await q.put(result)

    ender = asyncio.create_task(end_turn_after_quiet())
    try:
        await asyncio.wait_for(converse("test", state=state, config=config, show_output=False), timeout=5.0)
        await ender
    finally:
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer

    assert any("Model quiet" in n for n in captured_notes), f"expected a liveness note, got: {captured_notes}"


# --- Tool duration tracking via hooks ---


@pytest.mark.anyio
async def test_tool_hooks_track_active_tools():
    """PreToolUse adds to active_tools, PostToolUse removes and logs duration."""
    from claude_agent_sdk import HookContext
    from claude_agent_sdk.types import PostToolUseHookInput, PreToolUseHookInput

    from core import sdk_parsing

    state = vm.State()
    hooks = sdk_parsing.make_hooks(state)

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

    from core import sdk_parsing

    state = vm.State()
    hooks = sdk_parsing.make_hooks(state)

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


async def _run_converse_with_consumer(state, config, messages):
    """Drive one converse() turn with the real stream consumer fed from `messages`."""
    from core.client import consume_stream

    async def stream():
        for msg in messages:
            yield msg
        await asyncio.Event().wait()

    assert state.client is not None
    state.client.receive_messages = MagicMock(side_effect=lambda: stream())
    consumer = asyncio.create_task(consume_stream(state=state, config=config))
    try:
        await converse("test", state=state, config=config, show_output=False)
    finally:
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer


@pytest.mark.anyio
async def test_converse_touches_activity_on_messages():
    """The stream consumer updates last_sdk_activity when SDK messages arrive."""
    from claude_agent_sdk import ResultMessage

    state = vm.State()
    config = vm.VestaConfig(interrupt_timeout=0.5)

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    messages = []
    for _ in range(3):
        msg = MagicMock()
        msg.content = []
        messages.append(msg)
    result = MagicMock(spec=ResultMessage)
    result.content = []
    messages.append(result)

    await _run_converse_with_consumer(state, config, messages)

    assert state.last_sdk_activity_label == "sdk_message"


@pytest.mark.anyio
async def test_converse_clears_active_tools_on_start():
    """converse clears stale active_tools from prior calls."""
    from claude_agent_sdk import ResultMessage

    state = vm.State()
    config = vm.VestaConfig(interrupt_timeout=0.5)
    state.active_tools["stale"] = vm.ActiveTool(name="Old", summary="leftover", started_at=0)

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    result = MagicMock(spec=ResultMessage)
    result.content = []

    await _run_converse_with_consumer(state, config, [result])

    assert "stale" not in state.active_tools
