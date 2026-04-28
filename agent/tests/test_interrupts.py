"""Tests for interrupt system, converse streaming, and drain behavior."""

import asyncio
import typing as tp
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import core.models as vm
from claude_agent_sdk.types import SubagentStartHookInput
from core.client import _subagent_hook
from core.events import EventBus, SubagentStartEvent, SubagentStopEvent


# --- Subagent hooks ---


@pytest.mark.anyio
@pytest.mark.parametrize(
    "verb,event_type,agent_id,agent_type",
    [("started", "subagent_start", "test-123", "research"), ("stopped", "subagent_stop", "test-456", "browser")],
)
async def test_subagent_hook_emits_event(verb, event_type, agent_id, agent_type):
    from claude_agent_sdk import HookContext

    state = vm.State()
    hook = _subagent_hook(state, verb=verb, event_type=event_type)
    q = state.event_bus.subscribe()
    await hook(tp.cast(SubagentStartHookInput, {"agent_id": agent_id, "agent_type": agent_type}), None, tp.cast(HookContext, MagicMock()))
    received = tp.cast(SubagentStartEvent | SubagentStopEvent, q.get_nowait())
    assert received["type"] == event_type
    assert received["agent_id"] == agent_id
    assert received["agent_type"] == agent_type


# --- Converse harness ---


def _assistant_msg(content):
    from claude_agent_sdk import AssistantMessage

    msg = MagicMock(spec=AssistantMessage)
    msg.content = content
    return msg


def _result_msg():
    from claude_agent_sdk import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.content = []
    return msg


def _make_converse_harness(*, use_shared_queue: bool = False):
    """Build a converse() test harness with tracking and a mock SDK client."""
    import time

    emitted: list[tuple[str, float]] = []
    config = vm.VestaConfig(interrupt_timeout=0.5)
    state = vm.State()
    state.event_bus = EventBus()

    original_emit = state.event_bus.emit

    def tracking_emit(event):
        if isinstance(event, dict) and event.get("type") == "assistant":
            emitted.append((event["text"], time.monotonic()))
        original_emit(event)

    state.event_bus.emit = tracking_emit  # ty: ignore[invalid-assignment]

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    message_queue: asyncio.Queue[tp.Any] | None = None
    if use_shared_queue:
        message_queue = asyncio.Queue()

        async def _receive_response():
            from claude_agent_sdk import ResultMessage

            while True:
                msg = await message_queue.get()
                yield msg
                if isinstance(msg, ResultMessage):
                    return

        mock_client.receive_response = MagicMock(side_effect=lambda: _receive_response())

    return state, config, mock_client, emitted, message_queue


# --- Message processor interrupt ---


@pytest.mark.anyio
async def test_message_processor_interrupts_on_new_message(tmp_path):
    """New messages arriving during processing set the interrupt event and are processed after."""
    processing_started = asyncio.Event()
    interrupt_seen = asyncio.Event()

    async def slow_side_effect(msg, *, state, config, is_user):
        if "slow" in msg:
            processing_started.set()
            for _ in range(100):
                if state.interrupt_event and state.interrupt_event.is_set():
                    interrupt_seen.set()
                    break
                await asyncio.sleep(0.05)
        return (["OK"], state)

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    await queue.put(("slow processing message", True))

    processed: list[str] = []
    original = slow_side_effect

    async def tracking(msg, *, state, config, is_user):
        processed.append(msg)
        return await original(msg, state=state, config=config, is_user=is_user)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def inject_message_and_shutdown():
        await processing_started.wait()
        await queue.put(("urgent message", True))
        await interrupt_seen.wait()
        await asyncio.sleep(0.1)
        assert state.shutdown_event is not None
        state.shutdown_event.set()

    from core.loops import message_processor

    with (
        patch("core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("core.loops.process_message", tracking),
        patch("core.loops.build_client_options", return_value=MagicMock()),
    ):
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            inject_message_and_shutdown(),
        )

    assert interrupt_seen.is_set(), "interrupt_event should have been set when new message arrived"
    assert "slow processing message" in processed
    assert "urgent message" in processed


@pytest.mark.anyio
async def test_process_interruptible_cancels_process_task(tmp_path):
    """Cancelling _process_interruptible must cancel its in-flight process_task (no orphaned tasks)."""
    from core.loops import _process_interruptible

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    task_started = asyncio.Event()
    task_cancelled = False

    async def hanging_process(msg, *, state, config, is_user):
        nonlocal task_cancelled
        task_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            task_cancelled = True
            raise
        return (["OK"], state)

    with patch("core.loops._process_message_safely", hanging_process):
        interruptible_task = asyncio.create_task(_process_interruptible("test msg", is_user=True, queue=queue, state=state, config=config))
        await task_started.wait()
        interruptible_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await interruptible_task

    assert task_cancelled, "process_task should have been cancelled, not left orphaned"


@pytest.mark.anyio
async def test_process_interruptible_defers_interrupt_during_compaction(tmp_path):
    """While state.compacting is True, new messages must be queued, not interrupt the in-flight task."""
    from core.loops import _process_interruptible

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.compacting = True
    queue: asyncio.Queue = asyncio.Queue()

    processed: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_process(msg, *, state, config, is_user):
        processed.append(msg)
        if msg == "first":
            first_started.set()
            await release_first.wait()
        return (["OK"], state)

    with patch("core.loops._process_message_safely", fake_process):
        task = asyncio.create_task(_process_interruptible("first", is_user=True, queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(("second", True))
        await asyncio.sleep(0.1)
        assert processed == ["first"], "second must wait — interrupt was deferred"
        release_first.set()
        await task

    assert processed == ["first", "second"], f"second message must run after first, got: {processed}"


@pytest.mark.anyio
async def test_run_vesta_force_exits_on_hung_cleanup(tmp_path):
    """run_vesta must force-exit if task cleanup hangs (e.g. SDK __aexit__ blocking)."""
    from core.main import run_vesta

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()

    force_exit_called_with: list[int] = []
    exit_event = asyncio.Event()

    def fake_exit(code):
        force_exit_called_with.append(code)
        exit_event.set()

    async def hanging_on_cancel(*args, **kwargs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            while not exit_event.is_set():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    continue

    with (
        patch("core.main.start_ws_server", new_callable=AsyncMock) as mock_ws,
        patch("core.main.input_handler", hanging_on_cancel),
        patch("core.main.message_processor", hanging_on_cancel),
        patch("core.main.monitor_loop", hanging_on_cancel),
        patch("core.main.queue_greeting", new_callable=AsyncMock),
        patch("os._exit", fake_exit),
    ):
        mock_ws.return_value = MagicMock()
        mock_ws.return_value.cleanup = AsyncMock()

        async def trigger_shutdown():
            await asyncio.sleep(0.05)
            assert state.graceful_shutdown is not None
            state.graceful_shutdown.set()
            await exit_event.wait()

        await asyncio.gather(run_vesta(config, state=state), trigger_shutdown())

    assert force_exit_called_with == [1], f"os._exit(1) should have been called, got {force_exit_called_with}"


# --- Converse interrupt behavior ---


@pytest.mark.anyio
async def test_converse_breaks_on_interrupt_event():
    """converse exits promptly when interrupt_event is set."""
    from core.client import converse

    yielded_count = 0

    async def slow_response():
        nonlocal yielded_count
        msg = MagicMock()
        msg.content = []
        yielded_count += 1
        yield msg
        await asyncio.sleep(10)
        yielded_count += 1
        yield msg

    config = vm.VestaConfig(interrupt_timeout=0.5)
    state = vm.State()
    state.interrupt_event = asyncio.Event()

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=slow_response())
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    async def trigger_interrupt():
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()

    asyncio.create_task(trigger_interrupt())

    import time

    start = time.monotonic()
    await converse("test prompt", state=state, config=config, show_output=False)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"converse should have exited promptly but took {elapsed:.1f}s"
    assert mock_client.interrupt.called, "interrupt should have been called"
    assert yielded_count == 1, "should have only yielded once before interrupt"


@pytest.mark.anyio
async def test_converse_works_normally_without_interrupt():
    """converse processes all messages when no interrupt is set."""
    from core.client import converse

    messages_yielded = 0

    async def normal_response():
        nonlocal messages_yielded
        for _ in range(3):
            msg = MagicMock()
            msg.content = []
            messages_yielded += 1
            yield msg

    config = vm.VestaConfig()
    state = vm.State()

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=normal_response())
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    await converse("test prompt", state=state, config=config, show_output=False)

    assert messages_yielded == 3, "all messages should have been processed"
    assert not mock_client.interrupt.called, "interrupt should not have been called"


# --- Converse streaming regression tests ---


@pytest.mark.anyio
async def test_converse_emits_text_immediately_with_tool_use():
    """Text in messages that also have tool_use must be emitted immediately, not buffered."""
    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, _ = _make_converse_harness()

    async def response_with_tool_use():
        yield _assistant_msg([TextBlock("restarting daemon"), ToolUseBlock("1", "Bash", {})])
        yield _assistant_msg([TextBlock("checking status"), ToolUseBlock("2", "Bash", {})])
        yield _assistant_msg([TextBlock("all done")])

    mock_client.receive_response = MagicMock(return_value=response_with_tool_use())

    await converse("test", state=state, config=config, show_output=True)

    texts = [t for t, _ in emitted]
    assert texts == ["restarting daemon", "checking status", "all done"], f"All text must be emitted immediately, got: {texts}"


@pytest.mark.anyio
async def test_converse_emits_thinking_events():
    from claude_agent_sdk import TextBlock, ThinkingBlock
    from core.client import converse

    state, config, mock_client, emitted, _ = _make_converse_harness()
    thinking_events: list[tuple[str, str]] = []
    original_emit = state.event_bus.emit

    def tracking_emit(event):
        if isinstance(event, dict) and event.get("type") == "thinking":
            thinking_events.append((event["text"], event["signature"]))
        original_emit(event)

    state.event_bus.emit = tracking_emit

    async def response_with_thinking():
        yield _assistant_msg([ThinkingBlock("step one\nstep two", "sig-123"), TextBlock("done")])
        yield _result_msg()

    mock_client.receive_response = MagicMock(return_value=response_with_thinking())

    await converse("test", state=state, config=config, show_output=True)

    assert thinking_events == [("step one\nstep two", "sig-123")]
    assert [t for t, _ in emitted] == ["done"]


@pytest.mark.anyio
async def test_interrupt_drains_stream_and_emits_leftovers():
    """After an interrupt, leftover messages must be emitted (not lost)
    and must NOT leak into the next converse() call."""
    import time

    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    state.interrupt_event = asyncio.Event()

    async def sim_conv1():
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()
        await asyncio.sleep(0.1)
        await message_queue.put(_assistant_msg([TextBlock("here are the files")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv1())
    await converse("list /tmp", state=state, config=config, show_output=True)

    assert any(t == "here are the files" for t, _ in emitted), f"Leftover must be emitted during drain: {[t for t, _ in emitted]}"

    # Conv 2: must NOT see conv 1's leftovers
    state.interrupt_event = None
    n_before = len(emitted)

    async def sim_conv2():
        await asyncio.sleep(0.3)
        await message_queue.put(_assistant_msg([TextBlock("fresh response")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv2())
    t0 = time.monotonic()
    await converse("well?", state=state, config=config, show_output=True)

    conv2 = emitted[n_before:]
    assert len(conv2) == 1 and conv2[0][0] == "fresh response", f"Conv 2 got wrong messages: {[t for t, _ in conv2]}"
    delay_ms = (conv2[0][1] - t0) * 1000
    assert delay_ms > 100, f"Response at +{delay_ms:.0f}ms — too fast, likely leaked from conv 1"


@pytest.mark.anyio
async def test_interrupt_then_response_arrives_without_user_input():
    """Reproduces the exact bug from docker logs: user conversation is interrupted
    by a notification, notification does tool calls then responds -- that response
    must arrive on its own without the user sending another message."""
    import time

    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    state.interrupt_event = asyncio.Event()

    async def sim_conv1():
        await asyncio.sleep(0.05)
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()
        await asyncio.sleep(0.1)
        await message_queue.put(_assistant_msg([TextBlock("checking logs")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv1())
    await converse("i did it instantly", state=state, config=config, show_output=True)

    assert any(t == "checking logs" for t, _ in emitted), f"Conv 1 leftover not emitted: {[t for t, _ in emitted]}"

    state.interrupt_event = None
    n_before = len(emitted)
    t0 = time.monotonic()

    async def sim_conv2():
        await asyncio.sleep(0.05)
        await message_queue.put(_assistant_msg([ToolUseBlock("2", "Bash", {})]))
        await asyncio.sleep(0.2)
        await message_queue.put(_assistant_msg([TextBlock("daemon's back up")]))
        await asyncio.sleep(0.05)
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv2())
    await converse("daemon_died notification", state=state, config=config, show_output=True)

    conv2_texts = [t for t, _ in emitted[n_before:]]
    assert "daemon's back up" in conv2_texts, f"Conv 2 response must arrive without user interaction: {conv2_texts}"
    for text, t in emitted[n_before:]:
        if text == "daemon's back up":
            delay_ms = (t - t0) * 1000
            assert delay_ms < 2000, f"'{text}' took {delay_ms:.0f}ms — agent was stuck"


@pytest.mark.anyio
async def test_drain_timeout_does_not_block_forever():
    """If the SDK is slow to send ResultMessage after interrupt, the drain must
    time out and not block the next conversation forever."""
    from claude_agent_sdk import ToolUseBlock
    from core.client import converse

    state, config, mock_client, _, _ = _make_converse_harness()

    call_count = 0

    async def slow_drain_response():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield _assistant_msg([ToolUseBlock("1", "Bash", {})])
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(60)

    mock_client.receive_response = MagicMock(side_effect=lambda: slow_drain_response())
    state.client = mock_client
    state.interrupt_event = asyncio.Event()

    async def trigger():
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()

    import time

    asyncio.create_task(trigger())
    t0 = time.monotonic()
    await converse("test", state=state, config=config, show_output=True)
    elapsed = time.monotonic() - t0

    assert elapsed < 8.0, f"converse took {elapsed:.1f}s — drain blocked too long"
