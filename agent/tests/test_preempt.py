"""Tests for priority:"now" preemption (send_preempt), issue #982 and the 2026-07-14
delivery-is-completion redesign.

The SDK interrupt control request kills every backgrounded subagent in headless mode, so
preemption delivers the preempting prompt itself as a priority:"now" user message and never
touches the interrupt path (interrupt() fires only on failure paths; see test_interrupts.py).
A successful delivery is the prompt's whole lifecycle: the CLI guarantees no per-prompt
ResultMessage (it merges rapid queued prompts into one turn, starts turns of its own, and its
results carry no prompt identity), so no Vesta turn is ever opened for a delivered preempt and
its notification files clear at delivery."""

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import assistant_msg, consuming, make_stream_harness, result_msg
from wait_util import wait_for_condition

import core.models as vm
from core.notification import Notification


async def _sent_messages(mock_client) -> list[dict]:
    """Collect the message dicts from the async iterable passed to mock query()."""
    messages = []
    for call in mock_client.query.call_args_list:
        arg = call.args[0]
        if isinstance(arg, str):
            messages.append({"type": "string-query", "content": arg})
        else:
            messages.extend([m async for m in arg])
    return messages


# --- send_preempt ---


@pytest.mark.anyio
async def test_send_preempt_sends_priority_now_message_not_interrupt(config, state):
    from core.client import send_preempt

    state.client = MagicMock()
    state.client.query = AsyncMock()
    state.client.interrupt = AsyncMock()
    state.turn = vm.TurnSignals()

    assert await send_preempt("urgent notification", state=state, config=config)

    [message] = await _sent_messages(state.client)
    assert message["type"] == "user"
    assert message["priority"] == "now"
    assert message["parent_tool_use_id"] is None
    assert "urgent notification" in message["message"]["content"]
    assert state.turn.preempted, "a delivered preempt must mark the running turn preempted"
    state.client.interrupt.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("gate", ["no_client", "no_turn", "boot_turn", "compacting", "unauthenticated"])
async def test_send_preempt_gates_return_false_without_sending(config, state, gate):
    """Nothing to preempt (idle) or preemption barred (boot turn, compaction, dead token) -> queue normally."""
    from core.client import send_preempt
    from core.provider import ProviderAuthState, ProviderStatus

    if gate != "no_client":
        state.client = MagicMock()
        state.client.query = AsyncMock()
    if gate not in ("no_client", "no_turn"):
        state.turn = vm.TurnSignals()
    if gate == "boot_turn":
        state.noninterruptible_turn_active = True
    if gate == "compacting":
        state.compacting = True
    if gate == "unauthenticated":
        state.provider_status = ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind="claude", model="opus")

    assert not await send_preempt("notification", state=state, config=config)
    if state.turn is not None:
        assert not state.turn.preempted
    if state.client:
        state.client.query.assert_not_called()


@pytest.mark.anyio
async def test_send_preempt_write_failure_returns_false(config, state):
    """A failed pre-send degrades to normal queueing; it never aborts the caller."""
    from core.client import send_preempt

    state.client = MagicMock()
    state.client.query = AsyncMock(side_effect=RuntimeError("transport closed"))
    state.turn = vm.TurnSignals()

    assert not await send_preempt("notification", state=state, config=config)
    assert not state.turn.preempted


# --- converse (plain turns only) ---


@pytest.mark.anyio
async def test_converse_returns_turn_with_texts():
    from claude_agent_sdk import TextBlock

    from core.client import converse

    state, config, mock_client, _, message_queue, _ = make_stream_harness()
    async with consuming(state, config):
        task = asyncio.create_task(converse("hello", state=state, config=config, show_output=True))
        await wait_for_condition(lambda: state.turn is not None, message="converse never opened a turn")
        await message_queue.put(assistant_msg([TextBlock("reply")]))
        await message_queue.put(result_msg())
        turn = await asyncio.wait_for(task, timeout=5)

    assert turn.texts == ["reply"]
    assert not turn.preempted
    mock_client.query.assert_called_once()


@pytest.mark.anyio
async def test_dash_correction_skipped_for_preempted_turn():
    """A preempted turn's reply was cut short at a step boundary; the correction turn must not
    re-send it after the preempting prompt's work."""
    from claude_agent_sdk import TextBlock

    from core.client import process_message

    state, config, mock_client, _, message_queue, _ = make_stream_harness()

    async with consuming(state, config):
        task = asyncio.create_task(process_message("hi", state=state, config=config, is_user=False))
        await wait_for_condition(lambda: state.turn is not None, message="converse never opened a turn")
        state.turn.preempted = True  # what send_preempt records when it delivers mid-turn
        await message_queue.put(assistant_msg([TextBlock("bad — dash")]))
        await message_queue.put(result_msg())
        await asyncio.wait_for(task, timeout=5)

    assert mock_client.query.call_count == 1, "the dash correction must not run for a preempted turn"


# --- process_batch ---


def _notif(tmp_path, name: str, source: str = "whatsapp") -> Notification:
    f = tmp_path / f"{name}.json"
    f.write_text("x")
    return Notification(timestamp=dt.datetime(2025, 1, 1), source=source, type="message", body=name, file_path=str(f))


@pytest.mark.anyio
async def test_process_batch_renders_and_queues_sections_plain(config, state, tmp_path):
    """process_batch only renders and enqueues (system section first): preempt delivery is
    owned by the queue-watcher, so nothing is sent from here even mid-turn."""
    from core.loops import process_batch
    from core.notification import CORE_SOURCE

    state.client = MagicMock()
    state.client.query = AsyncMock()
    state.turn = vm.TurnSignals()
    queue: asyncio.Queue = asyncio.Queue()
    batch = [_notif(tmp_path, "sys", source=CORE_SOURCE), _notif(tmp_path, "ext")]

    with patch("core.loops.load_prompt", return_value=""):
        await process_batch(batch, queue=queue, config=config)

    state.client.query.assert_not_called()
    first, second = queue.get_nowait(), queue.get_nowait()
    assert "sys" in first.text and "ext" in second.text


# --- the queue-watcher: delivery is completion ---


def _blocking_processor():
    """A process_message fake whose "first" turn blocks until released:
    (fake_process, processed, first_started, release_first)."""
    processed: list[str] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_process(msg, *, state, config, is_user):
        processed.append(msg)
        if msg == "first":
            first_started.set()
            await release_first.wait()
        return ([], state)

    return fake_process, processed, first_started, release_first


@pytest.mark.anyio
async def test_watcher_delivery_consumes_item_and_clears_files(config, state, tmp_path):
    """A mid-turn item whose pre-send succeeds is consumed at delivery: files cleared,
    notification_cleared emitted, and no turn ever runs for it."""
    from core.loops import _run_messages_with_preempts

    queue: asyncio.Queue = asyncio.Queue()
    fake_process, processed, first_started, release_first = _blocking_processor()
    notif_file = tmp_path / "urgent.json"
    notif_file.write_text("{}")
    cleared: list[str] = []
    original_emit = state.event_bus.emit

    def tracking_emit(event):
        if isinstance(event, dict) and event.get("type") == "notification_cleared":
            cleared.append(event["notif_id"])
        original_emit(event)

    state.event_bus.emit = tracking_emit

    with patch("core.loops.process_message", fake_process), patch("core.loops.send_preempt", AsyncMock(return_value=True)):
        task = asyncio.create_task(_run_messages_with_preempts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("urgent", False, [str(notif_file)]))
        await wait_for_condition(lambda: not notif_file.exists(), message="delivered item's file never cleared")
        release_first.set()
        await task

    assert cleared == ["urgent"]
    assert processed == ["first"], f"a delivered item must never run as a turn: {processed}"


@pytest.mark.anyio
async def test_watcher_failed_delivery_queues_plain(config, state):
    """An undeliverable mid-turn item (inter-turn gap, failed write, gates) runs as an
    ordinary turn after the current one."""
    from core.loops import _run_messages_with_preempts

    queue: asyncio.Queue = asyncio.Queue()
    fake_process, processed, first_started, release_first = _blocking_processor()

    with patch("core.loops.process_message", fake_process), patch("core.loops.send_preempt", AsyncMock(return_value=False)):
        task = asyncio.create_task(_run_messages_with_preempts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("urgent", False, []))
        await wait_for_condition(queue.empty, message="watcher never collected the item")
        release_first.set()
        await task

    assert processed == ["first", "urgent"], f"an undelivered item must run as a plain turn: {processed}"


@pytest.mark.anyio
async def test_processor_collects_mid_turn_items_without_interrupting(config, state):
    """A mid-turn queue item never aborts the running turn from Vesta's side: the turn ends
    CLI-side (delivered preempt) or completes naturally, and an undelivered item runs next."""
    from core.loops import _run_messages_with_preempts

    queue: asyncio.Queue = asyncio.Queue()
    fake_process, processed, first_started, release_first = _blocking_processor()

    with patch("core.loops.process_message", fake_process), patch("core.loops.send_preempt", AsyncMock(return_value=False)):
        task = asyncio.create_task(_run_messages_with_preempts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("second", False, []))
        # Negative assertion: prove the watcher does NOT abort the running turn. Waiting for
        # absence requires a real time window; this sleep is intentional.
        await asyncio.sleep(0.1)
        assert processed == ["first"], "a mid-turn item must never abort the running turn"
        release_first.set()
        await task

    assert processed == ["first", "second"], f"the undelivered item must run next: {processed}"


# --- end to end: the 2026-07-14 incident (Beyonce test) ---


@pytest.mark.anyio
async def test_burst_of_preempts_with_merged_results_never_wedges(tmp_path):
    """The 2026-07-14 luna incident: several notifications preempt one running turn, the CLI
    merges them into that turn and answers with a single ResultMessage, and a CLI-initiated
    turn's result later arrives unmatched. The processor must consume every delivered item at
    delivery, never open a turn that waits on a merged-away result, and stay healthy for later
    work. Before the redesign this scenario wedged a phantom turn for 600s and crashed the
    agent with 'error: Response timed out'."""
    from claude_agent_sdk import TextBlock

    from core.loops import message_processor, process_batch

    state, config, mock_client, emitted, message_queue, _ = make_stream_harness()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(vm.QueuedTurn("first message", True, []))
    notifs = [_notif(tmp_path, f"burst-{i}") for i in range(3)]
    burst_files = [tmp_path / f"burst-{i}.json" for i in range(3)]

    with (
        patch("core.client.ClaudeSDKClient", return_value=mock_client),
        patch("core.client.build_client_options", return_value=MagicMock()),
        patch("core.loops.load_prompt", return_value=""),
    ):
        processor = asyncio.create_task(message_processor(queue, state=state, config=config))
        await wait_for_condition(lambda: state.turn is not None, message="first turn never opened")

        for notif in notifs:
            await process_batch([notif], queue=queue, config=config)
        await wait_for_condition(
            lambda: all(not f.exists() for f in burst_files),
            message="delivered preempts must clear their files at delivery",
        )
        assert state.turn is not None and state.turn.preempted

        # The CLI merges all three into the running turn and answers once.
        await message_queue.put(assistant_msg([TextBlock("merged reply")]))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: queue.empty() and not state.processor_busy, message="processor never drained after the merged result")
        assert state.turn is None, "no phantom turn may wait on a merged-away result"

        # A CLI-initiated turn's unmatched result arrives while idle: dropped, nothing wedges.
        await message_queue.put(result_msg())

        # The processor still round-trips later plain work.
        await queue.put(vm.QueuedTurn("later plain turn", True, []))
        await wait_for_condition(lambda: state.turn is not None, message="the later plain turn never opened")
        await message_queue.put(assistant_msg([TextBlock("plain reply")]))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: queue.empty() and not state.processor_busy, message="the later plain turn never completed")

        state.shutdown_event.set()
        await asyncio.wait_for(processor, timeout=5)

    assert not state.graceful_shutdown.is_set(), "the burst must not crash the agent"
    assert any("merged reply" in text for text, _ in emitted), f"merged output must stream: {emitted}"
    assert any("plain reply" in text for text, _ in emitted), f"later work must stream: {emitted}"


# --- turnless activity drives the state machine ---


@pytest.mark.anyio
async def test_turnless_stream_activity_drives_state():
    """Output with no open Vesta turn (a delivered preempt running as its own CLI turn, or a
    CLI-initiated turn) flips the activity state to thinking, and its result flips it back to
    idle. The state drives the snoozed-batch flush and the proactive gate, so it must track
    the stream, not Vesta's turn bookkeeping."""
    from claude_agent_sdk import TextBlock

    state, config, _, _, message_queue, _ = make_stream_harness()
    async with consuming(state, config):
        await message_queue.put(assistant_msg([TextBlock("turnless reply")]))
        await wait_for_condition(lambda: state.event_bus.state == "thinking", message="turnless activity never set thinking")
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: state.event_bus.state == "idle", message="turnless result never set idle")
