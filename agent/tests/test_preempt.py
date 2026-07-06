"""Tests for the default priority:"now" preemption (send_preempt + pre-sent turns) — issue #982.

The SDK interrupt control request kills every backgrounded subagent in headless mode, so the
default preempt mode delivers the preempting prompt itself as a priority:"now" user message and
never touches the interrupt path. The legacy interrupt mode keeps its coverage in
test_interrupts.py (pinned with config.preempt_mode = "interrupt")."""

import asyncio
import datetime as dt
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import core.models as vm
from conftest import assistant_msg, consuming, make_stream_harness, result_msg
from wait_util import wait_for_condition


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
    assert state.preempt_outstanding == 0
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


# --- converse with a pre-sent turn ---


@pytest.mark.anyio
async def test_converse_pre_sent_waits_without_second_query():
    from claude_agent_sdk import TextBlock

    from core.client import converse

    state, config, mock_client, _, message_queue, _ = make_stream_harness()
    async with consuming(state, config):
        task = asyncio.create_task(converse("already delivered", state=state, config=config, show_output=True, pre_sent=True))
        await wait_for_condition(lambda: state.turn is not None, message="pre-sent converse never opened a turn")
        await message_queue.put(assistant_msg([TextBlock("reply")]))
        await message_queue.put(result_msg())
        texts = await asyncio.wait_for(task, timeout=5)

    assert texts == ["reply"]
    mock_client.query.assert_not_called()


@pytest.mark.anyio
async def test_fast_preempt_result_is_banked_and_claimed_at_open():
    """A pre-sent turn whose ResultMessage lands before its Vesta turn opens must not stall
    converse until the silence timeout: the consumer banks the orphan and the pre-sent turn
    claims it at open, completing immediately."""
    from core.client import converse

    state, config, mock_client, _, message_queue, consumed = make_stream_harness()
    state.preempt_outstanding = 1

    async with consuming(state, config):
        # The fast preempt turn's result arrives while no Vesta turn is open.
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: len(consumed) == 1, message="consumer never dispatched the orphan result")
        assert state.preempt_orphaned_results == 1

        texts = await asyncio.wait_for(converse("already ran", state=state, config=config, show_output=True, pre_sent=True), timeout=5)

    assert texts == []
    assert state.preempt_outstanding == 0
    assert state.preempt_orphaned_results == 0
    mock_client.query.assert_not_called()


@pytest.mark.anyio
async def test_dash_correction_skipped_while_preempt_outstanding():
    """The correction query would land behind the queued preempt CLI-side while its Vesta turn
    opened first (crossed attribution) — with a preempt outstanding it must not be sent."""
    from claude_agent_sdk import TextBlock

    from core.client import process_message

    state, config, mock_client, _, message_queue, _ = make_stream_harness()

    async with consuming(state, config):
        task = asyncio.create_task(process_message("hi", state=state, config=config, is_user=False))
        await wait_for_condition(lambda: state.turn is not None, message="converse never opened a turn")
        state.preempt_outstanding = 1  # a preempt was delivered while this turn ran
        await message_queue.put(assistant_msg([TextBlock("bad — dash")]))
        await message_queue.put(result_msg())
        await asyncio.wait_for(task, timeout=5)

    sent = await _sent_messages(mock_client)
    assert len(sent) == 1, f"the dash correction must not be queried with a preempt outstanding: {sent}"


# --- process_batch in the default message mode ---


def _notif(tmp_path, name: str, source: str = "whatsapp") -> vm.Notification:
    f = tmp_path / f"{name}.json"
    f.write_text("x")
    return vm.Notification(timestamp=dt.datetime(2025, 1, 1), source=source, type="message", body=name, file_path=str(f))


@pytest.mark.anyio
async def test_process_batch_renders_and_queues_sections_plain(config, state, tmp_path):
    """process_batch only renders and enqueues (system section first): preempt delivery is
    owned by the queue-watcher, so nothing is sent or interrupted from here even mid-turn."""
    from core.loops import process_batch
    from core.models import CORE_SOURCE

    state.client = MagicMock()
    state.client.query = AsyncMock()
    state.turn = vm.TurnSignals()
    queue: asyncio.Queue = asyncio.Queue()
    batch = [_notif(tmp_path, "sys", source=CORE_SOURCE), _notif(tmp_path, "ext")]

    with patch("core.loops.attempt_interrupt", new_callable=AsyncMock) as mock_interrupt, patch("core.loops.load_prompt", return_value=""):
        await process_batch(batch, queue=queue, state=state, config=config)

    mock_interrupt.assert_not_called()
    state.client.query.assert_not_called()
    first, second = queue.get_nowait(), queue.get_nowait()
    assert not first.pre_sent and not second.pre_sent
    assert "sys" in first.text and "ext" in second.text


# --- end to end: notification preempts a running turn, no interrupt fired ---


@pytest.mark.anyio
async def test_notification_preempts_running_turn_end_to_end(tmp_path):
    """Default-mode preemption through the real processor, converse, and stream consumer: a
    notification arriving mid-turn is pre-sent, the running turn ends on the (fake) CLI-side
    abort's ResultMessage, and the pre-sent turn streams its reply — with the interrupt control
    request never fired. The CLI's actual priority:"now" abort semantics are covered by the
    live probe (issue #982), which this fake stands in for."""
    from claude_agent_sdk import TextBlock

    from core.loops import message_processor, process_batch

    state, config, mock_client, emitted, message_queue, _ = make_stream_harness()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(vm.QueuedTurn("first message", True, []))

    with (
        patch("core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("core.loops.build_client_options", return_value=MagicMock()),
        patch("core.loops.load_prompt", return_value=""),
    ):
        processor = asyncio.create_task(message_processor(queue, state=state, config=config))
        await wait_for_condition(lambda: state.turn is not None, message="first turn never opened")

        await process_batch([_notif(tmp_path, "urgent")], queue=queue, state=state, config=config)
        # The queue-watcher pre-sends the item as it lands mid-turn.
        await wait_for_condition(lambda: state.preempt_outstanding == 1, message="the watcher never pre-sent the notification")

        # The fake CLI aborts the running turn at its step boundary: its ResultMessage ends it.
        first_turn = state.turn
        await message_queue.put(result_msg())
        await wait_for_condition(
            lambda: state.turn is not None and state.turn is not first_turn and state.preempt_outstanding == 0,
            message="the pre-sent turn never opened",
        )
        await message_queue.put(assistant_msg([TextBlock("preempted reply")]))
        await message_queue.put(result_msg())
        await wait_for_condition(lambda: queue.empty() and not state.processor_busy, message="pre-sent turn never completed")

        state.shutdown_event.set()
        await asyncio.wait_for(processor, timeout=5)

    assert any("preempted reply" in text for text, _ in emitted), f"the preempt turn's reply must stream: {emitted}"
    mock_client.interrupt.assert_not_called()
    [pre_send] = [c for c in mock_client.query.call_args_list if not isinstance(c.args[0], str)]
    [sent] = [m async for m in pre_send.args[0]]
    assert sent["priority"] == "now"


# --- processor ordering + escalation in message mode ---


def _blocking_processor():
    """A process_message fake whose "first" turn blocks until released:
    (fake_process, processed, first_started, release_first)."""
    processed: list[tuple[str, bool]] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_process(msg, *, state, config, is_user, pre_sent=False):
        processed.append((msg, pre_sent))
        if msg == "first":
            first_started.set()
            await release_first.wait()
        return (["OK"], state)

    return fake_process, processed, first_started, release_first


@pytest.mark.anyio
async def test_processor_runs_pre_sent_items_before_earlier_plain_items(config, state):
    """A pre-sent item jumped the CLI's prompt queue (priority:"now"), so the processor must
    take it before plain items that queued earlier — otherwise Vesta's turn pairing crosses
    the CLI's actual turn order and notification files are cleared against the wrong turn."""
    from core.loops import _run_messages_with_interrupts

    queue: asyncio.Queue = asyncio.Queue()
    fake_process, processed, first_started, release_first = _blocking_processor()

    with patch("core.loops.process_message", fake_process), patch("core.loops.send_preempt", AsyncMock(return_value=False)):
        task = asyncio.create_task(_run_messages_with_interrupts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("plain", False, []))
        await queue.put(vm.QueuedTurn("preempt", False, [], pre_sent=True))
        await wait_for_condition(lambda: queue.empty(), message="watcher never collected the queued items")
        release_first.set()
        await task

    assert [m for m, _ in processed] == ["first", "preempt", "plain"], f"pre-sent item must jump plain items: {processed}"


@pytest.mark.anyio
async def test_watcher_retries_missed_presend_when_item_lands_mid_turn(config, state):
    """A producer's pre-send that missed (inter-turn gap, failed write) queues a plain item;
    when it lands while a turn is running, the watcher delivers the preempt itself."""
    from core.loops import _run_messages_with_interrupts

    queue: asyncio.Queue = asyncio.Queue()
    fake_process, processed, first_started, release_first = _blocking_processor()

    retried = AsyncMock(return_value=True)
    with patch("core.loops.process_message", fake_process), patch("core.loops.send_preempt", retried):
        task = asyncio.create_task(_run_messages_with_interrupts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("urgent", False, []))
        await wait_for_condition(lambda: retried.called, message="watcher never retried the pre-send")
        release_first.set()
        await task

    retried.assert_awaited_once_with("urgent", state=state, config=config)
    assert processed == [("first", False), ("urgent", True)], f"retried item must run pre-sent: {processed}"


# --- the processor never interrupts in message mode ---


@pytest.mark.anyio
async def test_processor_collects_mid_turn_items_without_interrupting(config, state):
    """In the default mode a mid-turn queue item never fires the interrupt path: the running
    turn ends CLI-side (pre-sent) or completes naturally (plain item), and the item runs next."""
    from core.loops import _run_messages_with_interrupts

    queue: asyncio.Queue = asyncio.Queue()
    fake_process, processed, first_started, release_first = _blocking_processor()

    with patch("core.loops.process_message", fake_process):
        task = asyncio.create_task(_run_messages_with_interrupts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("second", False, [], pre_sent=True))
        # Negative assertion: prove the watcher does NOT fire the interrupt path. Waiting for
        # absence requires a real time window; this sleep is intentional.
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None and not state.interrupt_event.is_set(), "message mode must never fire the interrupt path"
        # In production the pre-send has already ended the first turn CLI-side; the fake stands in for that.
        release_first.set()
        await task

    assert processed == [("first", False), ("second", True)], f"the pre-sent item must run next, with pre_sent forwarded: {processed}"
