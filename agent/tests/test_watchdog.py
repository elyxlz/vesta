"""Tests for SDK activity watchdog, tool duration tracking, and hang diagnostics."""

import asyncio
import tempfile
import time
import typing as tp
from unittest.mock import AsyncMock, MagicMock

import pytest
import core.models as vm
from core.cc_sdk import ClaudeAgentOptions, ClaudeSDKClient
from core.client import converse
from wait_util import wait_for_condition
from core.diagnostics import (
    _check_sdk_subprocess_alive,
    format_hang_diagnostics,
    format_pane_tail,
    longest_running_tool,
    sdk_idle_seconds,
    sdk_watchdog,
    touch_activity,
)


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


# --- format_pane_tail ---


def test_format_pane_tail_strips_ansi_and_box_drawing():
    pane = (
        "\x1b[2m  Searched for 1 pattern\x1b[0m\n"
        "\n"
        "──────────────────────────────\n"
        "\x1b[34m●\x1b[0m Services back up\n"
        "❯ yeah run it\n"
        "  ⏵⏵ bypass permissions on\n"
    )
    tail = format_pane_tail(pane)
    assert "❯ yeah run it" in tail
    assert "bypass permissions on" in tail
    assert "\x1b[" not in tail  # ANSI stripped
    assert "──────" not in tail  # Box-drawing rule dropped


def test_format_pane_tail_keeps_only_last_lines_and_caps_length():
    pane = "\n".join(f"content line number {i} here" for i in range(50))
    tail = format_pane_tail(pane)
    assert len(tail) <= 240
    assert "content line number 49 here" in tail
    assert "content line number 10 here" not in tail  # Only the tail survives


# --- _check_sdk_subprocess_alive ---
# Liveness is read through the client's public is_alive() accessor. The alive/dead
# distinction needs a launched claude process and lives in test_e2e_transport.py; the
# reachable-without-tmux cases (no client, and a constructed-but-unlaunched real client)
# are covered here.


def test_subprocess_alive_returns_none_when_no_client():
    state = vm.State()
    state.client = None
    assert _check_sdk_subprocess_alive(state) is None


def test_subprocess_alive_returns_none_before_launch():
    state = vm.State()
    state.client = ClaudeSDKClient(options=ClaudeAgentOptions(cwd=tempfile.mkdtemp()))
    assert _check_sdk_subprocess_alive(state) is None


# --- sdk_watchdog ---


@pytest.mark.anyio
async def test_watchdog_warns_at_thresholds():
    """Patch the sleep to 0 so the watchdog ticks immediately."""
    from unittest.mock import patch as _patch

    import core.diagnostics as diagnostics_mod

    state = vm.State()
    state.last_sdk_activity = time.monotonic() - 65  # Idle for 65s
    state.interrupt_event = asyncio.Event()  # Turn in flight, so silence is suspicious
    stop = asyncio.Event()
    warnings: list[str] = []

    original_warning = diagnostics_mod.logger.warning

    def capture_warning(msg):
        warnings.append(str(msg))

    diagnostics_mod.logger.warning = capture_warning  # ty: ignore[invalid-assignment]

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        return await original_wait_for(coro, timeout=0.01)

    try:

        async def stop_after_warning():
            await wait_for_condition(lambda: any("SDK silent for 60s" in w for w in warnings), message="watchdog never warned")
            stop.set()

        with _patch("core.diagnostics.asyncio.wait_for", fast_wait_for):
            await asyncio.gather(sdk_watchdog(state, stop=stop), stop_after_warning())
    finally:
        diagnostics_mod.logger.warning = original_warning

    assert any("SDK silent for 60s" in w for w in warnings), f"Expected 60s warning, got: {warnings}"


@pytest.mark.anyio
async def test_watchdog_warning_includes_pane_tail():
    """A suspicious silence captures the live claude pane so the warning shows what's wedged."""
    from unittest.mock import patch as _patch

    import core.diagnostics as diagnostics_mod

    state = vm.State()
    state.last_sdk_activity = time.monotonic() - 65  # Idle for 65s
    state.interrupt_event = asyncio.Event()  # Turn in flight, so silence is suspicious
    client = MagicMock()
    client.is_alive = MagicMock(return_value=True)
    client.snapshot_pane = AsyncMock(return_value="\x1b[34m●\x1b[0m wedged\n❯ yeah run it\n  ⏵⏵ bypass permissions on\n")
    state.client = client  # ty: ignore[invalid-assignment]
    stop = asyncio.Event()
    warnings: list[str] = []

    original_warning = diagnostics_mod.logger.warning
    diagnostics_mod.logger.warning = lambda msg: warnings.append(str(msg))  # ty: ignore[invalid-assignment]

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        return await original_wait_for(coro, timeout=0.05)

    try:

        async def stop_after_warning():
            await wait_for_condition(lambda: any("SDK silent for 60s" in w for w in warnings), message="watchdog never warned")
            stop.set()

        with _patch("core.diagnostics.asyncio.wait_for", fast_wait_for):
            await asyncio.gather(sdk_watchdog(state, stop=stop), stop_after_warning())
    finally:
        diagnostics_mod.logger.warning = original_warning

    silent = next(w for w in warnings if "SDK silent for 60s" in w)
    assert "pane_tail=" in silent
    assert "yeah run it" in silent


@pytest.mark.anyio
async def test_watchdog_resets_after_activity_resumes():
    from unittest.mock import patch as _patch

    import core.diagnostics as diagnostics_mod

    state = vm.State()
    state.last_sdk_activity = time.monotonic() - 65  # Idle
    state.interrupt_event = asyncio.Event()  # Turn in flight, so silence is suspicious
    stop = asyncio.Event()
    warnings: list[str] = []

    original_warning = diagnostics_mod.logger.warning

    def capture_warning(msg):
        warnings.append(str(msg))

    diagnostics_mod.logger.warning = capture_warning  # ty: ignore[invalid-assignment]

    original_wait_for = asyncio.wait_for
    ticks = 0

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        # One call per watchdog loop iteration; the idle check runs right after each call returns.
        nonlocal ticks
        ticks += 1
        return await original_wait_for(coro, timeout=0.01)

    def sixty_warning_count() -> int:
        return len([w for w in warnings if "SDK silent for 60s" in w])

    try:

        async def resume_then_idle_again():
            await wait_for_condition(lambda: sixty_warning_count() >= 1, message="watchdog never warned the first time")
            touch_activity(state, "sdk_message")
            # Wait two full ticks so at least one idle check definitely ran with the fresh
            # activity timestamp (clearing the watchdog's warned state), then go idle again.
            ticks_at_resume = ticks
            await wait_for_condition(lambda: ticks >= ticks_at_resume + 2, message="watchdog stopped ticking")
            state.last_sdk_activity = time.monotonic() - 65
            await wait_for_condition(lambda: sixty_warning_count() >= 2, message="watchdog never re-warned after reset")
            stop.set()

        with _patch("core.diagnostics.asyncio.wait_for", fast_wait_for):
            await asyncio.gather(sdk_watchdog(state, stop=stop), resume_then_idle_again())
    finally:
        diagnostics_mod.logger.warning = original_warning

    sixty_warnings = [w for w in warnings if "SDK silent for 60s" in w]
    assert len(sixty_warnings) >= 2, f"Expected 60s warning to fire again after reset, got {len(sixty_warnings)}: {warnings}"


@pytest.mark.anyio
async def test_watchdog_stops_cleanly():
    state = vm.State()
    stop = asyncio.Event()
    stop.set()  # Stop immediately
    await sdk_watchdog(state, stop=stop)  # Should not hang


@pytest.mark.anyio
async def test_watchdog_emits_error_event_once_per_threshold(tmp_path):
    """Crossing a watchdog threshold emits exactly one error event to the bus, not one per poll."""
    from unittest.mock import patch as _patch

    state = vm.State()
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    state.last_sdk_activity = time.monotonic() - 65  # Idle past the 60s threshold
    state.interrupt_event = asyncio.Event()  # Turn in flight, so silence is suspicious
    stop = asyncio.Event()
    seen: list[tp.Any] = []

    def sixty_events() -> list[str]:
        while not queue.empty():
            seen.append(queue.get_nowait())
        return [e["text"] for e in seen if e["type"] == "error" and "SDK silent for 60s" in e["text"]]

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        return await original_wait_for(coro, timeout=0.01)

    async def stop_after_some_polls():
        # Wait until the threshold has fired, then let several more polls run to prove
        # the event is emitted once per crossing rather than once per poll.
        await wait_for_condition(lambda: len(sixty_events()) >= 1, message="watchdog never emitted")
        for _ in range(5):
            await asyncio.sleep(0.02)
        stop.set()

    with _patch("core.diagnostics.asyncio.wait_for", fast_wait_for):
        await asyncio.gather(sdk_watchdog(state, stop=stop), stop_after_some_polls())

    assert len(sixty_events()) == 1, f"expected exactly one 60s error event, got {sixty_events()}"
    state.event_bus.close()


@pytest.mark.anyio
async def test_watchdog_stays_quiet_when_idle_between_turns(tmp_path):
    """No turn in flight + a live subprocess means silence is benign: log at debug, emit no error event."""
    from unittest.mock import patch as _patch

    import core.diagnostics as diagnostics_mod

    state = vm.State()
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    state.last_sdk_activity = time.monotonic() - 65  # Idle past the 60s threshold
    state.interrupt_event = None  # No turn in flight
    stop = asyncio.Event()
    warnings: list[str] = []

    original_warning = diagnostics_mod.logger.warning

    def capture_warning(msg):
        warnings.append(str(msg))

    diagnostics_mod.logger.warning = capture_warning  # ty: ignore[invalid-assignment]

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        return await original_wait_for(coro, timeout=0.01)

    def error_events() -> list[tp.Any]:
        events: list[tp.Any] = []
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "error" and "SDK silent" in event["text"]:
                events.append(event)
        return events

    try:

        async def let_several_polls_run():
            for _ in range(5):
                await asyncio.sleep(0.02)
            stop.set()

        with _patch("core.diagnostics.asyncio.wait_for", fast_wait_for):
            await asyncio.gather(sdk_watchdog(state, stop=stop), let_several_polls_run())
    finally:
        diagnostics_mod.logger.warning = original_warning

    assert not [w for w in warnings if "SDK silent" in w], f"expected no warnings while idle between turns, got {warnings}"
    assert error_events() == [], f"expected no error events while idle between turns, got {error_events()}"
    state.event_bus.close()


@pytest.mark.anyio
async def test_watchdog_stays_quiet_while_tool_runs(tmp_path):
    """A turn in flight is benign while a tool is actively running: a long `sleep` or build
    leaves the SDK silent without being hung, so log at debug and emit no error event."""
    from unittest.mock import patch as _patch

    import core.diagnostics as diagnostics_mod

    state = vm.State()
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    state.last_sdk_activity = time.monotonic() - 65  # Idle past the 60s threshold
    state.interrupt_event = asyncio.Event()  # Turn in flight...
    state.active_tools["tool-1"] = vm.ActiveTool(name="Bash", summary="sleep 180", started_at=time.monotonic() - 65)
    stop = asyncio.Event()
    warnings: list[str] = []

    original_warning = diagnostics_mod.logger.warning

    def capture_warning(msg):
        warnings.append(str(msg))

    diagnostics_mod.logger.warning = capture_warning  # ty: ignore[invalid-assignment]

    original_wait_for = asyncio.wait_for

    async def fast_wait_for(coro, *, timeout):  # type: ignore[no-untyped-def]
        return await original_wait_for(coro, timeout=0.01)

    def error_events() -> list[tp.Any]:
        events: list[tp.Any] = []
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "error" and "SDK silent" in event["text"]:
                events.append(event)
        return events

    try:

        async def let_several_polls_run():
            for _ in range(5):
                await asyncio.sleep(0.02)
            stop.set()

        with _patch("core.diagnostics.asyncio.wait_for", fast_wait_for):
            await asyncio.gather(sdk_watchdog(state, stop=stop), let_several_polls_run())
    finally:
        diagnostics_mod.logger.warning = original_warning

    assert not [w for w in warnings if "SDK silent" in w], f"expected no warnings while a tool is running, got {warnings}"
    assert error_events() == [], f"expected no error events while a tool is running, got {error_events()}"
    state.event_bus.close()


# --- Tool duration tracking via hooks ---


@pytest.mark.anyio
async def test_tool_hooks_track_active_tools():
    """PreToolUse adds to active_tools, PostToolUse removes and logs duration."""
    from core.cc_sdk import HookContext
    from core.cc_sdk.types import PostToolUseHookInput, PreToolUseHookInput

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
    from core.cc_sdk import HookContext
    from core.cc_sdk.types import PostToolUseFailureHookInput, PreToolUseHookInput

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
