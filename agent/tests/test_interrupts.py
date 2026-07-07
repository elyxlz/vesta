"""Tests for interrupt system, converse streaming, and drain behavior."""

import asyncio
import datetime as dt
import typing as tp
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import core.models as vm
from claude_agent_sdk.types import SubagentStartHookInput
from conftest import assistant_msg, consuming, idle_message_stream, make_stream_harness, result_msg
from core.sdk_parsing import _subagent_hook
from core.events import SubagentStartEvent, SubagentStopEvent
from wait_util import wait_for_condition


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


async def _set_interrupt_after_consumed(state, consumed, *, count: int = 1) -> None:
    """Fire the turn's interrupt only after the consumer has dispatched `count` messages."""
    await wait_for_condition(lambda: len(consumed) >= count, message="consumer never dispatched the first message")
    assert state.interrupt_event is not None
    state.interrupt_event.set()


async def _interrupt_then_winddown(state, mock_client, message_queue, consumed, *, winddown_text: str) -> None:
    """The #958 seed choreography: a tool message, an interrupt once it's consumed, then the
    interrupted turn's wind-down (text + result) once converse has fired client.interrupt()."""
    from claude_agent_sdk import TextBlock, ToolUseBlock

    await message_queue.put(assistant_msg([ToolUseBlock("1", "Bash", {})]))
    await _set_interrupt_after_consumed(state, consumed)
    await wait_for_condition(lambda: mock_client.interrupt.called, message="converse never called interrupt()")
    await message_queue.put(assistant_msg([TextBlock(winddown_text)]))
    await message_queue.put(result_msg())


# --- Message processor interrupt ---


@pytest.mark.anyio
async def test_message_processor_interrupts_on_new_message(config, state):
    """New messages arriving during processing set the interrupt event and are processed after."""
    from core.provider import ProviderAuthState, ProviderStatus

    config.preempt_mode = "interrupt"
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    processing_started = asyncio.Event()
    interrupt_seen = asyncio.Event()

    async def slow_side_effect(msg, *, state, config, is_user, pre_sent=False):
        if "slow" in msg:
            processing_started.set()
            await wait_for_condition(lambda: state.interrupt_event is not None and state.interrupt_event.is_set())
            interrupt_seen.set()
        return (["OK"], state)

    queue: asyncio.Queue = asyncio.Queue()

    await queue.put(vm.QueuedTurn("slow processing message", True, []))

    processed: list[str] = []
    original = slow_side_effect

    async def tracking(msg, *, state, config, is_user, pre_sent=False):
        processed.append(msg)
        return await original(msg, state=state, config=config, is_user=is_user)

    mock_client = MagicMock()
    mock_client.receive_messages = idle_message_stream
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def inject_message_and_shutdown():
        await processing_started.wait()
        await queue.put(vm.QueuedTurn("urgent message", True, []))
        await interrupt_seen.wait()
        await wait_for_condition(lambda: "urgent message" in processed, message="urgent message never processed after interrupt")
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
async def test_message_processor_sets_busy_flag_during_turn(config, state):
    """processor_busy is True while a turn runs and False once it finishes (gates the proactive check)."""
    from core.provider import ProviderAuthState, ProviderStatus

    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    processing_started = asyncio.Event()
    busy_during_turn = False

    async def slow_side_effect(msg, *, state, config, is_user, pre_sent=False):
        nonlocal busy_during_turn
        busy_during_turn = state.processor_busy
        processing_started.set()
        return (["OK"], state)

    queue: asyncio.Queue = asyncio.Queue()

    await queue.put(vm.QueuedTurn("message", True, []))

    mock_client = MagicMock()
    mock_client.receive_messages = idle_message_stream
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def shutdown_after_turn():
        await processing_started.wait()
        await wait_for_condition(lambda: not state.processor_busy, message="turn never finished")
        state.shutdown_event.set()

    from core.loops import message_processor

    with (
        patch("core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("core.loops.process_message", slow_side_effect),
        patch("core.loops.build_client_options", return_value=MagicMock()),
    ):
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            shutdown_after_turn(),
        )

    assert busy_during_turn, "processor_busy should be True while a turn is processing"
    assert not state.processor_busy, "processor_busy should be cleared once the turn finishes"


@pytest.mark.anyio
async def test_run_messages_with_interrupts_cancels_process_task(config, state):
    """Cancelling _run_messages_with_interrupts must cancel its in-flight process_task (no orphaned tasks)."""
    from core.loops import _run_messages_with_interrupts

    queue: asyncio.Queue = asyncio.Queue()

    task_started = asyncio.Event()
    task_cancelled = False

    async def hanging_process(msg, *, state, config, is_user, pre_sent=False):
        nonlocal task_cancelled
        task_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            task_cancelled = True
            raise
        return (["OK"], state)

    with patch("core.loops.process_message", hanging_process):
        interruptible_task = asyncio.create_task(
            _run_messages_with_interrupts(vm.QueuedTurn("test msg", True, []), queue=queue, state=state, config=config)
        )
        await task_started.wait()
        interruptible_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await interruptible_task

    assert task_cancelled, "process_task should have been cancelled, not left orphaned"


@pytest.mark.anyio
async def test_non_interruptible_boot_turn_is_not_preempted(config, state):
    """A boot turn (interruptible=False) runs to completion; a message queued mid-turn waits its turn."""
    from core.loops import _run_messages_with_interrupts

    queue: asyncio.Queue = asyncio.Queue()
    processed: list[str] = []
    boot_started = asyncio.Event()
    release_boot = asyncio.Event()

    async def fake_process(msg, *, state, config, is_user, pre_sent=False):
        processed.append(msg)
        if msg == "boot":
            boot_started.set()
            await release_boot.wait()
        return (["OK"], state)

    with patch("core.loops.process_message", fake_process):
        task = asyncio.create_task(
            _run_messages_with_interrupts(vm.QueuedTurn("boot", False, [], interruptible=False), queue=queue, state=state, config=config)
        )
        await boot_started.wait()
        await queue.put(vm.QueuedTurn("user message", True, []))
        # The boot turn must not be interrupted: the interrupt event stays unset and the message waits.
        await asyncio.sleep(0.1)
        assert processed == ["boot"], "the queued message must not preempt the boot turn"
        assert state.interrupt_event is not None and not state.interrupt_event.is_set()
        release_boot.set()
        await task

    assert processed == ["boot", "user message"], f"the queued message must run after the boot turn, got: {processed}"


@pytest.mark.anyio
async def test_process_batch_does_not_sdk_abort_a_boot_turn(config, state, tmp_path):
    """While a non-interruptible boot turn is in flight, process_batch must NOT fire client.interrupt()
    (the SDK-level path), but must still queue the batch so it runs after the boot turn."""
    from core.loops import process_batch

    config.preempt_mode = "interrupt"
    state.client = MagicMock()  # a live SDK client; attempt_interrupt would otherwise abort the turn
    state.noninterruptible_turn_active = True
    queue: asyncio.Queue = asyncio.Queue()

    notif_file = tmp_path / "n.json"
    notif_file.write_text("x")
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="whatsapp", type="message", file_path=str(notif_file))

    with patch("core.loops.attempt_interrupt", new_callable=AsyncMock) as mock_interrupt, patch("core.loops.load_prompt", return_value=""):
        await process_batch([notif], queue=queue, state=state, config=config)

    mock_interrupt.assert_not_called()
    assert not queue.empty(), "the notification batch must still be queued to run after the boot turn"


@pytest.mark.anyio
async def test_process_batch_sdk_aborts_a_normal_turn(config, state, tmp_path):
    """The gate is specific to boot turns: with no boot turn in flight, process_batch still interrupts."""
    from core.loops import process_batch

    config.preempt_mode = "interrupt"
    state.client = MagicMock()
    state.noninterruptible_turn_active = False
    queue: asyncio.Queue = asyncio.Queue()

    notif_file = tmp_path / "n.json"
    notif_file.write_text("x")
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="whatsapp", type="message", file_path=str(notif_file))

    with patch("core.loops.attempt_interrupt", new_callable=AsyncMock) as mock_interrupt, patch("core.loops.load_prompt", return_value=""):
        await process_batch([notif], queue=queue, state=state, config=config)

    mock_interrupt.assert_called_once()


@pytest.mark.anyio
async def test_run_messages_with_interrupts_defers_interrupt_during_compaction(config, state):
    """While state.compacting is True, new messages must be queued, not interrupt the in-flight task."""
    from core.loops import _run_messages_with_interrupts

    config.preempt_mode = "interrupt"
    state.compacting = True
    queue: asyncio.Queue = asyncio.Queue()

    processed: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_process(msg, *, state, config, is_user, pre_sent=False):
        processed.append(msg)
        if msg == "first":
            first_started.set()
            await release_first.wait()
        return (["OK"], state)

    with patch("core.loops.process_message", fake_process):
        task = asyncio.create_task(_run_messages_with_interrupts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("second", True, []))
        # Negative assertion: prove "second" does NOT run while compaction holds the interrupt.
        # Waiting for absence requires a real time window; this sleep is intentional.
        await asyncio.sleep(0.1)
        assert processed == ["first"], "second must wait — interrupt was deferred"
        release_first.set()
        await task

    assert processed == ["first", "second"], f"second message must run after first, got: {processed}"


@pytest.mark.anyio
async def test_run_vesta_force_exits_on_hung_cleanup(config, state):
    """run_vesta must force-exit if task cleanup hangs (e.g. SDK __aexit__ blocking)."""
    from core.main import run_vesta

    config.data_dir.mkdir(parents=True, exist_ok=True)

    force_exit_called_with: list[int] = []
    exit_event = asyncio.Event()
    started_tasks: list[bool] = []

    def fake_exit(code):
        force_exit_called_with.append(code)
        exit_event.set()

    async def hanging_on_cancel(*args, **kwargs):
        started_tasks.append(True)
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
        patch("core.main.message_processor", hanging_on_cancel),
        patch("core.main.monitor_loop", hanging_on_cancel),
        patch("core.main.collect_boot_turns", return_value=[]),
        patch("os._exit", fake_exit),
    ):
        mock_ws.return_value = MagicMock()
        mock_ws.return_value.cleanup = AsyncMock()

        async def trigger_shutdown():
            # Both patched workers (message_processor, monitor_loop) running
            # means run_vesta is fully started and waiting on graceful_shutdown.
            await wait_for_condition(lambda: len(started_tasks) >= 2, message="run_vesta worker tasks never started")
            assert state.graceful_shutdown is not None
            state.graceful_shutdown.set()
            await exit_event.wait()

        await asyncio.gather(run_vesta(config, state=state), trigger_shutdown())

    assert force_exit_called_with == [1], f"os._exit(1) should have been called, got {force_exit_called_with}"


# --- attempt_interrupt escalation ---


@pytest.mark.anyio
async def test_attempt_interrupt_timeout_warns_without_sigterm(tmp_path, state, event_bus):
    """When client.interrupt() times out, attempt_interrupt warns and returns False
    instead of SIGTERMing the process.

    The 5s timeout fires more often during heavy thinking than during a real hang, so a
    false-positive must not kill the whole container; converse's response-timeout path owns
    ending a genuinely dead turn (see issue #737)."""
    from core.client import attempt_interrupt

    config = vm.VestaConfig(agent_dir=tmp_path / "agent", interrupt_timeout=0.01)
    state.event_bus = event_bus
    queue = event_bus.subscribe()

    mock_client = MagicMock()

    async def interrupt_times_out():
        # asyncio.TimeoutError is the builtin TimeoutError in 3.11+; attempt_interrupt catches it.
        raise TimeoutError

    mock_client.interrupt = interrupt_times_out
    state.client = mock_client

    kills: list[tuple[int, int]] = []
    exits: list[int] = []

    def fake_kill(pid, sig):
        kills.append((pid, sig))

    def fake_exit(code):
        exits.append(code)

    with (
        patch("core.client.os.kill", fake_kill),
        patch("core.client.os._exit", fake_exit),
    ):
        result = await attempt_interrupt(state, config=config, reason="hung SDK")

    assert result is False, "a timed-out interrupt must report failure, not success"
    assert kills == [], f"timed-out interrupt must not SIGTERM the process, got {kills}"
    assert exits == [], f"timed-out interrupt must not force-exit, got {exits}"

    events: list[str] = []
    while not queue.empty():
        event = queue.get_nowait()
        if event["type"] == "error":
            events.append(event["text"])
    assert len(events) == 1, f"a timed-out interrupt must surface exactly one event, got {events}"
    assert "SDK interrupt timed out" in events[0]


@pytest.mark.anyio
async def test_attempt_interrupt_fires_while_tool_in_flight(tmp_path, state, event_bus):
    """attempt_interrupt still asks the SDK to interrupt while a tool is executing. The SDK
    services the request at its next yield point; a timeout no longer SIGTERMs (see issue #737),
    so there is no reason to suppress the interrupt during tool work."""
    from core.client import attempt_interrupt

    config = vm.VestaConfig(agent_dir=tmp_path / "agent", interrupt_timeout=0.01)
    state.event_bus = event_bus
    state.active_tools["tool-1"] = vm.ActiveTool(name="Bash", summary="ls", started_at=0.0)

    interrupted = False

    async def interrupt():
        nonlocal interrupted
        interrupted = True

    mock_client = MagicMock()
    mock_client.interrupt = interrupt
    state.client = mock_client

    result = await attempt_interrupt(state, config=config, reason="notification")

    assert result is True, "a serviced interrupt must report success"
    assert interrupted is True, "client.interrupt() must be called even while a tool is in flight"


# --- Converse under the long-lived stream consumer ---


@pytest.mark.anyio
async def test_converse_collects_texts_and_ends_on_result():
    """A normal turn: converse returns every text the consumer attributed to it, in order."""
    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()

    async with consuming(state, config):
        await message_queue.put(assistant_msg([TextBlock("one")]))
        await message_queue.put(assistant_msg([TextBlock("two")]))
        await message_queue.put(result_msg())
        responses = await converse("test prompt", state=state, config=config, show_output=True)

    assert responses == ["one", "two"]
    assert [t for t, _ in emitted] == ["one", "two"]
    assert not mock_client.interrupt.called


@pytest.mark.anyio
async def test_converse_emits_text_immediately_with_tool_use():
    """Text in messages that also have tool_use must be emitted immediately, not buffered."""
    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()

    async with consuming(state, config):
        await message_queue.put(assistant_msg([TextBlock("restarting daemon"), ToolUseBlock("1", "Bash", {})]))
        await message_queue.put(assistant_msg([TextBlock("checking status"), ToolUseBlock("2", "Bash", {})]))
        await message_queue.put(assistant_msg([TextBlock("all done")]))
        await message_queue.put(result_msg())
        await converse("test", state=state, config=config, show_output=True)

    texts = [t for t, _ in emitted]
    assert texts == ["restarting daemon", "checking status", "all done"], f"All text must be emitted immediately, got: {texts}"


@pytest.mark.anyio
async def test_converse_emits_thinking_events():
    from claude_agent_sdk import TextBlock, ThinkingBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()
    thinking_events: list[tuple[str, str]] = []
    original_emit = state.event_bus.emit

    def tracking_emit(event):
        if isinstance(event, dict) and event.get("type") == "thinking":
            thinking_events.append((event["text"], event["signature"]))
        original_emit(event)

    state.event_bus.emit = tracking_emit

    async with consuming(state, config):
        await message_queue.put(assistant_msg([ThinkingBlock("step one\nstep two", "sig-123"), TextBlock("done")]))
        await message_queue.put(result_msg())
        await converse("test", state=state, config=config, show_output=True)

    assert thinking_events == [("step one\nstep two", "sig-123")]
    assert [t for t, _ in emitted] == ["done"]


@pytest.mark.anyio
async def test_converse_exits_promptly_on_interrupt_event():
    """converse interrupts and returns within the bounded grace even when the interrupted turn's
    ResultMessage never arrives (the CLI wind-down outliving the grace is the #958 seed)."""
    import time

    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()
    state.interrupt_event = asyncio.Event()

    async with consuming(state, config):
        await message_queue.put(assistant_msg([TextBlock("working on it")]))
        trigger = asyncio.create_task(_set_interrupt_after_consumed(state, consumed))
        with patch("core.client._INTERRUPT_TURN_END_GRACE_S", 0.1):
            start = time.monotonic()
            responses = await converse("test prompt", state=state, config=config, show_output=True)
            elapsed = time.monotonic() - start
        await trigger

    assert elapsed < 2.0, f"converse should have exited promptly but took {elapsed:.1f}s"
    assert mock_client.interrupt.called, "interrupt should have been called"
    assert responses == ["working on it"]


@pytest.mark.anyio
async def test_interrupt_winddown_within_grace_stays_attributed():
    """A wind-down that finishes inside the grace is emitted AND attributed to the interrupted
    turn, and the next turn starts against a clean stream."""
    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()
    state.interrupt_event = asyncio.Event()

    async with consuming(state, config):
        sim = asyncio.create_task(_interrupt_then_winddown(state, mock_client, message_queue, consumed, winddown_text="here are the files"))
        responses = await converse("list /tmp", state=state, config=config, show_output=True)
        await sim

        assert responses == ["here are the files"], f"wind-down text must be attributed to the interrupted turn: {responses}"
        assert any(t == "here are the files" for t, _ in emitted), f"wind-down text must be emitted: {[t for t, _ in emitted]}"

        # Conv 2: starts clean, gets exactly its own messages.
        state.interrupt_event = None
        n_before = len(emitted)

        async def sim_conv2():
            await wait_for_condition(lambda: mock_client.query.await_count >= 2, message="conv 2 query never sent")
            await message_queue.put(assistant_msg([TextBlock("fresh response")]))
            await message_queue.put(result_msg())

        sim2 = asyncio.create_task(sim_conv2())
        responses2 = await converse("well?", state=state, config=config, show_output=True)
        await sim2

    assert responses2 == ["fresh response"], f"Conv 2 got wrong messages: {responses2}"
    assert [t for t, _ in emitted[n_before:]] == ["fresh response"]


@pytest.mark.anyio
async def test_interrupt_then_response_arrives_without_user_input():
    """Reproduces the #958 user-visible bug: a notification turn interrupts the conversation, does
    tool calls, then responds — that response must arrive on its own, without another user poke."""
    import time

    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()
    state.interrupt_event = asyncio.Event()

    async with consuming(state, config):
        sim = asyncio.create_task(_interrupt_then_winddown(state, mock_client, message_queue, consumed, winddown_text="checking logs"))
        await converse("i did it instantly", state=state, config=config, show_output=True)
        await sim

        assert any(t == "checking logs" for t, _ in emitted), f"Conv 1 wind-down not emitted: {[t for t, _ in emitted]}"

        state.interrupt_event = None
        n_before = len(emitted)
        t0 = time.monotonic()

        async def sim_conv2():
            consumed_before = len(consumed)
            await message_queue.put(assistant_msg([ToolUseBlock("2", "Bash", {})]))
            await wait_for_condition(lambda: len(consumed) > consumed_before, message="conv 2 tool message never consumed")
            await message_queue.put(assistant_msg([TextBlock("daemon's back up")]))
            await message_queue.put(result_msg())

        sim2 = asyncio.create_task(sim_conv2())
        await converse("daemon_died notification", state=state, config=config, show_output=True)
        await sim2

    conv2_texts = [t for t, _ in emitted[n_before:]]
    assert "daemon's back up" in conv2_texts, f"Conv 2 response must arrive without user interaction: {conv2_texts}"
    for text, t in emitted[n_before:]:
        if text == "daemon's back up":
            delay_ms = (t - t0) * 1000
            assert delay_ms < 2000, f"'{text}' took {delay_ms:.0f}ms — agent was stuck"


@pytest.mark.anyio
async def test_late_result_after_interrupt_does_not_wedge_later_turns():
    """The #958 regression: an interrupted turn's ResultMessage lands after the grace, during the
    next turn. That next turn's label closes early (advisory), but every message still reaches the
    user in real time, the stray result is dropped, and the stream self-heals by the turn after."""
    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()

    async with consuming(state, config):
        with patch("core.client._INTERRUPT_TURN_END_GRACE_S", 0.1):
            # Turn 1: interrupted; its wind-down outlives the grace (no result arrives).
            state.interrupt_event = asyncio.Event()
            await message_queue.put(assistant_msg([TextBlock("turn one partial")]))
            trigger = asyncio.create_task(_set_interrupt_after_consumed(state, consumed))
            await converse("turn one", state=state, config=config, show_output=True)
            await trigger
            assert mock_client.interrupt.called

        # Turn 2: turn 1's stale result lands mid-turn and closes its label early.
        state.interrupt_event = None
        conv2 = asyncio.create_task(converse("turn two", state=state, config=config, show_output=True))
        await wait_for_condition(lambda: mock_client.query.await_count >= 2, message="turn 2 query never sent")
        stale_result = result_msg()
        await message_queue.put(stale_result)
        await conv2  # closed by the stale result — must not hang

        # Turn 2's real output arrives after its label closed: still emitted in real time...
        n_before = len(emitted)
        await message_queue.put(assistant_msg([TextBlock("turn two answer")]))
        await wait_for_condition(
            lambda: any(t == "turn two answer" for t, _ in emitted[n_before:]),
            message="post-close output was not emitted — this is the wedge #958 describes",
        )
        # ...and its own result, arriving with no open turn, is dropped without harm.
        own_result = result_msg()
        await message_queue.put(own_result)
        await wait_for_condition(lambda: own_result in consumed, message="stray result never consumed")

        # Turn 3: fully self-healed — a normal turn completes end-to-end.
        async def feed_turn3():
            await wait_for_condition(lambda: mock_client.query.await_count >= 3, message="turn 3 query never sent")
            await message_queue.put(assistant_msg([TextBlock("turn three answer")]))
            await message_queue.put(result_msg())

        feeder = asyncio.create_task(feed_turn3())
        responses3 = await converse("turn three", state=state, config=config, show_output=True)
        await feeder

    assert responses3 == ["turn three answer"], f"stream did not self-heal: {responses3}"


@pytest.mark.anyio
async def test_result_with_no_open_turn_is_dropped():
    """An unprompted ResultMessage (a self-initiated CLI continuation turn) arriving while idle is
    dropped, its text still emitted, and the next real turn is unaffected."""
    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()

    async with consuming(state, config):
        # Idle: a continuation turn's output + result arrive with no query outstanding.
        continuation_text = assistant_msg([TextBlock("background task finished")])
        continuation_result = result_msg()
        await message_queue.put(continuation_text)
        await message_queue.put(continuation_result)
        await wait_for_condition(lambda: continuation_result in consumed, message="continuation messages never consumed")
        assert any(t == "background task finished" for t, _ in emitted), "idle output must still reach the user"

        # The next real turn sees only its own messages.
        async def feed():
            await wait_for_condition(lambda: mock_client.query.await_count >= 1, message="query never sent")
            await message_queue.put(assistant_msg([TextBlock("real answer")]))
            await message_queue.put(result_msg())

        feeder = asyncio.create_task(feed())
        responses = await converse("real question", state=state, config=config, show_output=True)
        await feeder

    assert responses == ["real answer"], f"continuation result leaked into the next turn: {responses}"


@pytest.mark.anyio
async def test_converse_raises_when_stream_dies_mid_turn():
    """A stream death mid-turn surfaces through the open turn so run_one's restart path fires."""
    from claude_agent_sdk import ClaudeSDKError, TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness()

    async def dying_stream():
        yield assistant_msg([TextBlock("partial")])
        raise ClaudeSDKError("subprocess died")

    mock_client.receive_messages = MagicMock(side_effect=lambda: dying_stream())

    async with consuming(state, config):
        with pytest.raises(ClaudeSDKError, match="subprocess died"):
            await converse("test", state=state, config=config, show_output=True)


@pytest.mark.anyio
async def test_converse_times_out_on_stream_silence():
    """No stream message for response_timeout ends the turn with TimeoutError (restart path),
    same silence budget the per-message wait enforced before the consumer restructure."""
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = make_stream_harness(response_timeout=1)

    async with consuming(state, config):
        with pytest.raises(TimeoutError):
            await converse("test", state=state, config=config, show_output=True)

    assert mock_client.interrupt.called, "a response timeout must attempt to interrupt the hung turn"


@pytest.mark.anyio
async def test_compact_session_waits_for_result(config):
    """compact_session blocks until the compaction turn's ResultMessage closes the turn."""
    from claude_agent_sdk import SystemMessage
    from core.client import compact_session

    state, _, mock_client, emitted, message_queue, consumed = make_stream_harness()

    async with consuming(state, config):
        boundary = SystemMessage(subtype="compact_boundary", data={"compact_metadata": {"pre_tokens": 1000, "trigger": "manual"}})
        await message_queue.put(boundary)
        await message_queue.put(result_msg())
        await asyncio.wait_for(compact_session(state=state), timeout=5.0)

    mock_client.query.assert_awaited_once_with("/compact")
    assert state.turn is None


@pytest.mark.anyio
async def test_compact_session_collapses_multiline_prompt_to_one_line(config):
    """A slash command is a single line: multi-line guidance is collapsed so nothing after the
    first newline is truncated by the CLI parser."""
    from claude_agent_sdk import SystemMessage
    from core.client import compact_session

    state, _, mock_client, emitted, message_queue, consumed = make_stream_harness()

    async with consuming(state, config):
        boundary = SystemMessage(subtype="compact_boundary", data={"compact_metadata": {"pre_tokens": 1000, "trigger": "manual"}})
        await message_queue.put(boundary)
        await message_queue.put(result_msg())
        multiline = "keep open threads\nand this draft:\nline two"
        await asyncio.wait_for(compact_session(state=state, prompt=multiline), timeout=5.0)

    mock_client.query.assert_awaited_once_with("/compact keep open threads and this draft: line two")
    assert state.turn is None


def test_read_compaction_summary_extracts_latest(tmp_path, monkeypatch):
    """The /compact summary is read back from the session transcript for logging: pick the latest
    isCompactSummary entry and join its text blocks."""
    import json
    import pathlib as pl
    from core import client

    proj = tmp_path / ".claude" / "projects" / "-root-agent"
    proj.mkdir(parents=True)
    lines = [
        {"type": "assistant", "message": {"content": "not a summary"}},
        {"isCompactSummary": True, "message": {"content": [{"type": "text", "text": "an older summary"}]}},
        {"isCompactSummary": True, "message": {"content": [{"type": "text", "text": "the latest summary"}]}},
    ]
    (proj / "sess-xyz.jsonl").write_text("\n".join(json.dumps(line) for line in lines))
    monkeypatch.setattr(pl.Path, "home", lambda: tmp_path)

    assert client._read_compaction_summary("sess-xyz") == "the latest summary"


def test_read_compaction_summary_returns_none_when_absent(tmp_path, monkeypatch):
    import pathlib as pl
    from core import client

    monkeypatch.setattr(pl.Path, "home", lambda: tmp_path)
    assert client._read_compaction_summary("no-such-session") is None


# --- Converse auth handling ---


@pytest.mark.anyio
async def test_converse_flips_to_unauthenticated_on_claude_401(config):
    """A terminal Claude api-error turn (401) flips the provider to not_authenticated, interrupts the
    CLI's retries, and ends the turn cleanly (no exception -> no restart loop)."""
    from claude_agent_sdk import AssistantMessage, TextBlock
    from core.client import converse
    from core.provider import ProviderAuthState, ProviderStatus

    config.data_dir.mkdir(parents=True, exist_ok=True)
    state, _, mock_client, emitted, message_queue, consumed = make_stream_harness()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    async with consuming(state, config):
        await message_queue.put(
            AssistantMessage(
                content=[TextBlock(text="Please run /login · API Error: 401 Invalid authentication credentials")],
                model="opus",
                error="authentication_failed",
            )
        )
        await asyncio.wait_for(converse("test prompt", state=state, config=config, show_output=False), timeout=5.0)

    # The flip is in-memory only (no persisted auth flag); the live status reflects it this session.
    assert state.provider_status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert state.provider_status.model is None
    assert mock_client.interrupt.called, "should interrupt the CLI's retries on auth loss"


@pytest.mark.anyio
async def test_converse_ignores_transient_api_error(config):
    """A transient api-error turn (502) must NOT flip auth — it resolves on retry."""
    from claude_agent_sdk import AssistantMessage, TextBlock
    from core.client import converse
    from core.provider import ProviderAuthState, ProviderStatus

    config.data_dir.mkdir(parents=True, exist_ok=True)
    state, _, mock_client, emitted, message_queue, consumed = make_stream_harness()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    async with consuming(state, config):
        await message_queue.put(
            AssistantMessage(
                content=[TextBlock(text="API Error: 502 Bad Gateway. This is a server-side issue, usually temporary")],
                model="opus",
                error="server_error",
            )
        )
        await message_queue.put(result_msg())
        await asyncio.wait_for(converse("test prompt", state=state, config=config, show_output=False), timeout=5.0)

    assert state.provider_status.state == ProviderAuthState.AUTHENTICATED
    assert not mock_client.interrupt.called


@pytest.mark.anyio
async def test_converse_flips_auth_on_result_api_error_status(config):
    """A terminal 401/402 may surface on the ResultMessage's HTTP status rather than the assistant
    turn's error field; that must still flip the agent to not_authenticated."""
    from claude_agent_sdk import ResultMessage
    from core.client import converse
    from core.provider import ProviderAuthState, ProviderStatus

    config.data_dir.mkdir(parents=True, exist_ok=True)
    state, _, mock_client, emitted, message_queue, consumed = make_stream_harness()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    async with consuming(state, config):
        await message_queue.put(
            ResultMessage(
                subtype="error_during_execution",
                duration_ms=100,
                duration_api_ms=80,
                is_error=True,
                num_turns=1,
                session_id="sess-xyz",
                api_error_status=401,
            )
        )
        await asyncio.wait_for(converse("test prompt", state=state, config=config, show_output=False), timeout=5.0)

    assert state.provider_status.state == ProviderAuthState.NOT_AUTHENTICATED
