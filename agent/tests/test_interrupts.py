"""Tests for interrupt system, converse streaming, and drain behavior."""

import asyncio
import datetime as dt
import typing as tp
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import core.models as vm
from claude_agent_sdk.types import SubagentStartHookInput
from core.sdk_parsing import _subagent_hook
from core.events import EventBus, SubagentStartEvent, SubagentStopEvent
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
    """Build a converse() test harness with tracking and a mock SDK client.

    Returns (state, config, mock_client, emitted, message_queue, consumed). `consumed`
    records each queued message right after converse's stream loop receives it, giving
    tests a handshake signal ("converse has seen message N") instead of guessing with sleeps.
    """
    import time

    emitted: list[tuple[str, float]] = []
    config = vm.VestaConfig(interrupt_timeout=0.5)
    state = vm.State()
    # message_processor runs the client loop only for an authenticated provider; these interrupt tests
    # drive that loop, so mark the agent authenticated.
    from core.provider import ProviderAuthState, ProviderStatus

    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
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
    consumed: list[tp.Any] = []
    if use_shared_queue:
        message_queue = asyncio.Queue()

        async def _receive_response():
            from claude_agent_sdk import ResultMessage

            while True:
                msg = await message_queue.get()
                yield msg
                # The generator only resumes here once the consumer's async-for advanced
                # past `msg` — i.e. converse has genuinely received it.
                consumed.append(msg)
                if isinstance(msg, ResultMessage):
                    return

        mock_client.receive_response = MagicMock(side_effect=lambda: _receive_response())

    return state, config, mock_client, emitted, message_queue, consumed


# --- Message processor interrupt ---


@pytest.mark.anyio
async def test_message_processor_interrupts_on_new_message(config, state):
    """New messages arriving during processing set the interrupt event and are processed after."""
    from core.provider import ProviderAuthState, ProviderStatus

    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    processing_started = asyncio.Event()
    interrupt_seen = asyncio.Event()

    async def slow_side_effect(msg, *, state, config, is_user):
        if "slow" in msg:
            processing_started.set()
            await wait_for_condition(lambda: state.interrupt_event is not None and state.interrupt_event.is_set())
            interrupt_seen.set()
        return (["OK"], state)

    queue: asyncio.Queue = asyncio.Queue()

    await queue.put(vm.QueuedTurn("slow processing message", True, []))

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

    async def slow_side_effect(msg, *, state, config, is_user):
        nonlocal busy_during_turn
        busy_during_turn = state.processor_busy
        processing_started.set()
        return (["OK"], state)

    queue: asyncio.Queue = asyncio.Queue()

    await queue.put(vm.QueuedTurn("message", True, []))

    mock_client = MagicMock()
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

    async def hanging_process(msg, *, state, config, is_user):
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

    async def fake_process(msg, *, state, config, is_user):
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
    false-positive must not kill the whole container; the diagnostics watchdog owns the
    genuinely-stuck-idle SIGTERM path (see issue #737)."""
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

    state, config, mock_client, *_ = _make_converse_harness()
    state.interrupt_event = asyncio.Event()
    mock_client.receive_response = MagicMock(return_value=slow_response())

    async def trigger_interrupt():
        await wait_for_condition(lambda: yielded_count == 1, message="converse never consumed the first message")
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

    state, config, mock_client, *_ = _make_converse_harness()
    mock_client.receive_response = MagicMock(return_value=normal_response())

    await converse("test prompt", state=state, config=config, show_output=False)

    assert messages_yielded == 3, "all messages should have been processed"
    assert not mock_client.interrupt.called, "interrupt should not have been called"


@pytest.mark.anyio
async def test_converse_flips_to_unauthenticated_on_claude_401(config):
    """A terminal Claude api-error turn (401) flips the provider to not_authenticated, interrupts the
    CLI's retries, and ends the turn cleanly (no exception -> no restart loop)."""
    from core.client import converse
    from claude_agent_sdk import AssistantMessage, TextBlock
    from core.provider import ProviderAuthState, ProviderStatus

    config.data_dir.mkdir(parents=True, exist_ok=True)

    async def auth_error_response():
        yield AssistantMessage(
            content=[TextBlock(text="Please run /login · API Error: 401 Invalid authentication credentials")],
            model="opus",
            error="authentication_failed",
        )
        # A second message would only arrive if converse failed to break.
        await asyncio.sleep(10)
        yield AssistantMessage(content=[TextBlock(text="should never be reached")], model="opus")

    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=auth_error_response())
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    await converse("test prompt", state=state, config=config, show_output=False)

    # The flip is in-memory only (no persisted auth flag); the live status reflects it this session.
    assert state.provider_status.state == ProviderAuthState.NOT_AUTHENTICATED
    assert state.provider_status.model is None
    assert mock_client.interrupt.called, "should interrupt the CLI's retries on auth loss"


@pytest.mark.anyio
async def test_converse_ignores_transient_api_error(config):
    """A transient api-error turn (502) must NOT flip auth — it resolves on retry."""
    from core.client import converse
    from claude_agent_sdk import AssistantMessage, TextBlock
    from core.provider import ProviderAuthState, ProviderStatus

    config.data_dir.mkdir(parents=True, exist_ok=True)

    async def transient_error_response():
        yield AssistantMessage(
            content=[TextBlock(text="API Error: 502 Bad Gateway. This is a server-side issue, usually temporary")],
            model="opus",
            error="server_error",
        )

    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=transient_error_response())
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    await converse("test prompt", state=state, config=config, show_output=False)

    assert state.provider_status.state == ProviderAuthState.AUTHENTICATED
    assert not mock_client.interrupt.called


@pytest.mark.anyio
async def test_converse_flips_auth_on_result_api_error_status(config):
    """A terminal 401/402 may surface on the ResultMessage's HTTP status rather than the assistant
    turn's error field; that must still flip the agent to not_authenticated."""
    from core.client import converse
    from claude_agent_sdk import ResultMessage
    from core.provider import ProviderAuthState, ProviderStatus

    config.data_dir.mkdir(parents=True, exist_ok=True)

    async def auth_error_result():
        yield ResultMessage(
            subtype="error_during_execution",
            duration_ms=100,
            duration_api_ms=80,
            is_error=True,
            num_turns=1,
            session_id="sess-xyz",
            api_error_status=401,
        )

    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=auth_error_result())
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    await converse("test prompt", state=state, config=config, show_output=False)

    assert state.provider_status.state == ProviderAuthState.NOT_AUTHENTICATED


# --- Converse streaming regression tests ---


@pytest.mark.anyio
async def test_converse_emits_text_immediately_with_tool_use():
    """Text in messages that also have tool_use must be emitted immediately, not buffered."""
    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, _, _ = _make_converse_harness()

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

    state, config, mock_client, emitted, _, _ = _make_converse_harness()
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

    state, config, mock_client, emitted, message_queue, consumed = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    state.interrupt_event = asyncio.Event()

    async def sim_conv1():
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        # Handshake: converse received the tool message, now interrupt it.
        await wait_for_condition(lambda: len(consumed) >= 1, message="converse never consumed the tool message")
        assert state.interrupt_event is not None
        state.interrupt_event.set()
        # Handshake: converse reacted to the interrupt; the drain window is open for leftovers.
        await wait_for_condition(lambda: mock_client.interrupt.called, message="converse never called interrupt()")
        await message_queue.put(_assistant_msg([TextBlock("here are the files")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv1())
    await converse("list /tmp", state=state, config=config, show_output=True)

    assert any(t == "here are the files" for t, _ in emitted), f"Leftover must be emitted during drain: {[t for t, _ in emitted]}"

    # Conv 2: must NOT see conv 1's leftovers
    state.interrupt_event = None
    n_before = len(emitted)
    fresh_put_at: list[float] = []

    async def sim_conv2():
        # Adversarial window: if conv 1's leftovers leaked into conv 2, they would surface
        # here, before "fresh response" is even queued.
        await asyncio.sleep(0.3)
        fresh_put_at.append(time.monotonic())
        await message_queue.put(_assistant_msg([TextBlock("fresh response")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv2())
    await converse("well?", state=state, config=config, show_output=True)

    conv2 = emitted[n_before:]
    assert len(conv2) == 1 and conv2[0][0] == "fresh response", f"Conv 2 got wrong messages: {[t for t, _ in conv2]}"
    assert conv2[0][1] >= fresh_put_at[0], "Response was emitted before sim_conv2 queued it — leaked from conv 1"


@pytest.mark.anyio
async def test_interrupt_then_response_arrives_without_user_input():
    """Reproduces the exact bug from docker logs: user conversation is interrupted
    by a notification, notification does tool calls then responds -- that response
    must arrive on its own without the user sending another message."""
    import time

    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    state.interrupt_event = asyncio.Event()

    async def sim_conv1():
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        await wait_for_condition(lambda: len(consumed) >= 1, message="converse never consumed the tool message")
        assert state.interrupt_event is not None
        state.interrupt_event.set()
        await wait_for_condition(lambda: mock_client.interrupt.called, message="converse never called interrupt()")
        await message_queue.put(_assistant_msg([TextBlock("checking logs")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv1())
    await converse("i did it instantly", state=state, config=config, show_output=True)

    assert any(t == "checking logs" for t, _ in emitted), f"Conv 1 leftover not emitted: {[t for t, _ in emitted]}"

    state.interrupt_event = None
    n_before = len(emitted)
    t0 = time.monotonic()

    async def sim_conv2():
        # Simulates the notification turn: a tool call, then the response, paced by
        # what converse has actually consumed rather than by wall-clock guesses.
        consumed_before = len(consumed)
        await message_queue.put(_assistant_msg([ToolUseBlock("2", "Bash", {})]))
        await wait_for_condition(lambda: len(consumed) > consumed_before, message="conv 2 tool message never consumed")
        await message_queue.put(_assistant_msg([TextBlock("daemon's back up")]))
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

    state, config, mock_client, _, _, _ = _make_converse_harness()

    call_count = 0
    first_message_consumed = asyncio.Event()

    async def slow_drain_response():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            yield _assistant_msg([ToolUseBlock("1", "Bash", {})])
            # Resumed = converse advanced past the first message.
            first_message_consumed.set()
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(60)

    mock_client.receive_response = MagicMock(side_effect=lambda: slow_drain_response())
    state.client = mock_client
    state.interrupt_event = asyncio.Event()

    async def trigger():
        await first_message_consumed.wait()
        assert state.interrupt_event is not None
        state.interrupt_event.set()

    import time

    asyncio.create_task(trigger())
    t0 = time.monotonic()
    await converse("test", state=state, config=config, show_output=True)
    elapsed = time.monotonic() - t0

    assert elapsed < 8.0, f"converse took {elapsed:.1f}s — drain blocked too long"


@pytest.mark.anyio
async def test_late_result_after_drain_timeout_does_not_desync_next_turn():
    """Reproduces the stream desync from the 2026-07-02 logs: a turn is interrupted but the
    CLI winds down slower than the drain window, so the turn's tail (including its
    ResultMessage) lands in the stream after converse abandoned it. The next converse must
    still deliver ITS OWN response — a stale ResultMessage from the abandoned turn must not
    terminate the new turn instantly (which leaves every subsequent turn off by one: the
    agent looks hung, and each new user message flushes the previous turn's output)."""
    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    state.interrupt_event = asyncio.Event()

    async def sim_conv1():
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        # Handshake: converse received the tool message, now interrupt it. The queue stays
        # empty through the drain window — the CLI is "still thinking" and winds down late.
        await wait_for_condition(lambda: len(consumed) >= 1, message="converse never consumed the tool message")
        assert state.interrupt_event is not None
        state.interrupt_event.set()

    sim_task = asyncio.create_task(sim_conv1())
    with patch("core.client._INTERRUPT_DRAIN_TIMEOUT_S", 0.05):
        await converse("update whatsmeow", state=state, config=config, show_output=True)
    await sim_task

    # The CLI finishes the abandoned turn late: its tail + ResultMessage arrive after the
    # drain gave up. Then the next turn's real response follows on the same stream.
    await message_queue.put(_assistant_msg([TextBlock("late tail of the abandoned turn")]))
    await message_queue.put(_result_msg())
    await message_queue.put(_assistant_msg([TextBlock("fresh response")]))
    await message_queue.put(_result_msg())

    state.interrupt_event = None
    responses = await converse("eta?", state=state, config=config, show_output=True)

    assert any("fresh response" in r for r in responses), (
        f"conv 2 must sync to its own result, not terminate on the abandoned turn's stale ResultMessage; got responses={responses}"
    )
    assert not any("late tail" in r for r in responses), (
        f"the abandoned turn's late tail must not be attributed to conv 2's responses; got responses={responses}"
    )
    assert any(t == "late tail of the abandoned turn" for t, _ in emitted), "the late tail must still be emitted (shown), just not attributed"


@pytest.mark.anyio
async def test_phantom_outstanding_result_ends_the_turn_instead_of_hanging():
    """A results_outstanding count whose result never comes (an abandoned query the CLI dropped)
    must not make converse skip the live turn's own result and hang to response_timeout: past the
    stale-result window, the stream is trusted over the count and the bookkeeping is reset."""
    import time

    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None
    state.results_outstanding = 1  # phantom: no result for this will ever arrive

    async def sim():
        # Past the (patched) stale window, so the result must be trusted as the live turn's own.
        await asyncio.sleep(0.2)
        await message_queue.put(_assistant_msg([TextBlock("real answer")]))
        await message_queue.put(_result_msg())

    sim_task = asyncio.create_task(sim())
    t0 = time.monotonic()
    with patch("core.client._STALE_RESULT_WINDOW_S", 0.05):
        await converse("hello", state=state, config=config, show_output=True)
    elapsed = time.monotonic() - t0
    await sim_task

    assert elapsed < 5.0, f"converse hung {elapsed:.1f}s on a phantom outstanding count"
    assert state.results_outstanding == 0, "a phantom count must be hard-reset when the stream is trusted over it"
    assert any(t == "real answer" for t, _ in emitted), "the live turn's text must still be shown"


@pytest.mark.anyio
async def test_interrupt_drain_total_budget_bounds_a_chatty_wind_down():
    """The post-interrupt drain is bounded overall, not just per read: a wind-down streaming
    messages steadily (each inside the per-read cap) while more than one result is outstanding
    must not hold the interrupting user's new turn hostage."""
    import time

    from claude_agent_sdk import TextBlock, ToolUseBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None
    state.results_outstanding = 1  # a prior abandoned turn is still owed a result
    state.interrupt_event = asyncio.Event()
    feeding = True

    async def sim():
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        await wait_for_condition(lambda: len(consumed) >= 1, message="converse never consumed the tool message")
        assert state.interrupt_event is not None
        state.interrupt_event.set()
        # Chatty wind-down: messages keep arriving inside the per-read cap, never a result.
        while feeding:
            await message_queue.put(_assistant_msg([TextBlock("still winding down")]))
            await asyncio.sleep(0.05)

    sim_task = asyncio.create_task(sim())
    t0 = time.monotonic()
    with patch("core.client._INTERRUPT_DRAIN_TIMEOUT_S", 0.5), patch("core.client._INTERRUPT_DRAIN_TOTAL_S", 0.3):
        await converse("guarded", state=state, config=config, show_output=True)
    elapsed = time.monotonic() - t0
    feeding = False
    await sim_task

    assert elapsed < 2.0, f"the drain must respect its total budget; took {elapsed:.1f}s"


@pytest.mark.anyio
async def test_unprompted_continuation_result_does_not_end_the_next_turn():
    """The CLI runs self-initiated turns (background-task continuations) ending in ResultMessages no
    query ever counted (verified against CLI 2.1.187). One buffered ahead of the next turn must not
    terminate that turn: a result this early cannot be the turn's own (a real result needs an API
    round trip), so converse confirms with a bounded peek and keeps reading its actual response."""
    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    # The continuation's block is already buffered when the user's next message arrives.
    await message_queue.put(_assistant_msg([TextBlock("background task completed")]))
    await message_queue.put(_result_msg())

    async def sim_real_turn():
        # The real turn streams shortly after (well inside the confirmation window).
        await asyncio.sleep(0.2)
        await message_queue.put(_assistant_msg([TextBlock("actual reply")]))
        await message_queue.put(_result_msg())

    sim_task = asyncio.create_task(sim_real_turn())
    with patch("core.client._EARLY_RESULT_SUSPECT_S", 1.0), patch("core.client._EARLY_RESULT_CONFIRM_S", 2.0):
        responses = await converse("hello", state=state, config=config, show_output=True)
    await sim_task

    assert any("actual reply" in r for r in responses), (
        f"the turn must survive the unprompted continuation result and return its own reply; got responses={responses}"
    )
    assert not any("background task completed" in r for r in responses), (
        f"the continuation's content must not be attributed to this turn; got responses={responses}"
    )
    assert any(t == "background task completed" for t, _ in emitted), "the continuation's text must still be shown"


@pytest.mark.anyio
async def test_early_result_with_nothing_following_ends_the_turn():
    """The confirmation peek is bounded: when a suspiciously early result is followed by silence,
    it really was the turn's own (a very fast turn) and converse ends instead of hanging."""
    import time

    from claude_agent_sdk import TextBlock
    from core.client import converse

    state, config, mock_client, emitted, message_queue, consumed = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    await message_queue.put(_assistant_msg([TextBlock("quick reply")]))
    await message_queue.put(_result_msg())

    t0 = time.monotonic()
    with patch("core.client._EARLY_RESULT_SUSPECT_S", 1.0), patch("core.client._EARLY_RESULT_CONFIRM_S", 0.2):
        responses = await converse("hi", state=state, config=config, show_output=True)
    elapsed = time.monotonic() - t0

    assert elapsed < 3.0, f"the confirmation peek must be bounded; converse took {elapsed:.1f}s"
    assert any("quick reply" in r for r in responses), f"a genuinely fast turn must keep its reply; got responses={responses}"
