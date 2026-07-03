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
    note_turn_liveness,
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


# --- note_turn_liveness ---


def _quiet_turn(quiet_s: float) -> vm.TurnSignals:
    turn = vm.TurnSignals()
    turn.last_visible_at = time.monotonic() - quiet_s
    return turn


def test_liveness_notes_once_per_threshold(captured_notes, state):
    turn = _quiet_turn(65)
    noted: set[int] = set()

    note_turn_liveness(state, turn=turn, noted_at=noted)
    note_turn_liveness(state, turn=turn, noted_at=noted)

    assert len([n for n in captured_notes if "quiet for 60s" in n]) == 1, f"one note per crossing, got: {captured_notes}"
    assert noted == {60}


def test_liveness_notes_each_threshold_as_quiet_grows(captured_notes, state):
    turn = _quiet_turn(65)
    noted: set[int] = set()

    note_turn_liveness(state, turn=turn, noted_at=noted)
    turn.last_visible_at = time.monotonic() - 125
    note_turn_liveness(state, turn=turn, noted_at=noted)

    quiet_notes = [n for n in captured_notes if "quiet" in n]
    assert len(quiet_notes) == 2 and "60s" in quiet_notes[0] and "120s" in quiet_notes[1], f"expected 60s then 120s, got: {captured_notes}"


def test_liveness_resets_when_output_lands(captured_notes, state):
    turn = _quiet_turn(65)
    noted: set[int] = set()

    note_turn_liveness(state, turn=turn, noted_at=noted)
    turn.last_visible_at = time.monotonic()  # output emitted
    note_turn_liveness(state, turn=turn, noted_at=noted)
    assert noted == set()

    turn.last_visible_at = time.monotonic() - 65
    note_turn_liveness(state, turn=turn, noted_at=noted)

    assert len([n for n in captured_notes if "quiet for 60s" in n]) == 2, f"expected a re-note after output, got: {captured_notes}"


def test_liveness_reports_thinking_with_token_count(captured_notes, captured_warnings, state, tmp_path):
    """A recently ticking thinking counter makes the note specific — and is never escalated,
    however long the think runs: the model is demonstrably reasoning, not stalled."""
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    turn = _quiet_turn(305)
    turn.thinking_tokens = 2340
    turn.thinking_tokens_at = time.monotonic() - 5
    noted: set[int] = set()

    note_turn_liveness(state, turn=turn, noted_at=noted)

    thinking_notes = [n for n in captured_notes if "Thinking for" in n and "2,340 tokens" in n]
    assert len(thinking_notes) == 3, f"expected token-count notes at 60/120/300, got: {captured_notes}"
    assert captured_warnings == [], f"healthy thinking must never warn, got: {captured_warnings}"
    assert queue.empty(), "healthy thinking must not emit error events"
    state.event_bus.close()


def test_liveness_escalates_dead_air_past_escalation(captured_warnings, captured_notes, state, tmp_path):
    """No output AND no thinking ticks past the escalation threshold is a suspected stall:
    one warning + one error event."""
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    turn = _quiet_turn(305)  # no thinking_tokens ever seen
    noted: set[int] = set()

    note_turn_liveness(state, turn=turn, noted_at=noted)
    note_turn_liveness(state, turn=turn, noted_at=noted)

    warnings_300 = [w for w in captured_warnings if "no stream activity for 300s" in w]
    assert len(warnings_300) == 1, f"expected exactly one 300s warning, got: {captured_warnings}"
    events = []
    while not queue.empty():
        event = queue.get_nowait()
        if event["type"] == "error" and "no stream activity" in event["text"]:
            events.append(event)
    assert len(events) == 1, f"expected exactly one error event, got: {events}"
    # The earlier thresholds stay calm INFO notes, not warnings.
    assert len([n for n in captured_notes if "quiet" in n]) == 2, f"60s+120s notes expected, got: {captured_notes}"
    state.event_bus.close()


def test_liveness_stays_debug_while_tool_runs(captured_warnings, captured_notes, state, tmp_path):
    """A running tool explains the quiet (a long build, a sleep): no notes, no warnings, no events."""
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    state.active_tools["tool-1"] = vm.ActiveTool(name="Bash", summary="sleep 180", started_at=time.monotonic() - 305)
    turn = _quiet_turn(305)
    noted: set[int] = set()

    note_turn_liveness(state, turn=turn, noted_at=noted)

    assert [n for n in captured_notes if "quiet" in n or "Thinking" in n] == [], f"expected no notes mid-tool, got: {captured_notes}"
    assert captured_warnings == [], f"expected no warnings mid-tool, got: {captured_warnings}"
    assert queue.empty(), "expected no error events mid-tool"
    state.event_bus.close()


@pytest.mark.anyio
async def test_converse_notes_thinking_while_waiting(captured_notes, monkeypatch):
    """End to end through the wait loop: thinking_tokens system messages keep the turn's counter
    fresh while producing no visible output, and the liveness note reports the token count."""
    import core.client as client_mod
    import core.diagnostics as diagnostics_mod
    from claude_agent_sdk import ResultMessage, SystemMessage
    from core.client import consume_stream

    monkeypatch.setattr(client_mod, "_SILENCE_POLL_S", 0.02)
    monkeypatch.setattr(diagnostics_mod, "_QUIET_THRESHOLDS_S", (0,))

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

    async def think_then_finish():
        await q.put(SystemMessage(subtype="thinking_tokens", data={"estimated_tokens": 312, "estimated_tokens_delta": 5}))
        await wait_for_condition(
            lambda: any("Thinking for" in n and "312 tokens" in n for n in captured_notes),
            message="no thinking note during quiet stretch",
        )
        result = MagicMock(spec=ResultMessage)
        result.content = []
        await q.put(result)

    thinker = asyncio.create_task(think_then_finish())
    try:
        await asyncio.wait_for(converse("test", state=state, config=config, show_output=False), timeout=5.0)
        await thinker
    finally:
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer

    assert any("Thinking for" in n for n in captured_notes), f"expected a thinking note, got: {captured_notes}"


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
