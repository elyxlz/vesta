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
@pytest.mark.parametrize("gate", ["no_client", "no_turn", "boot_turn", "compacting"])
async def test_send_preempt_gates_return_false_without_sending(config, state, gate):
    """Nothing to preempt (idle) or preemption barred (boot turn, compaction) -> queue normally."""
    from core.client import send_preempt

    if gate != "no_client":
        state.client = MagicMock()
        state.client.query = AsyncMock()
    if gate not in ("no_client", "no_turn"):
        state.turn = vm.TurnSignals()
    if gate == "boot_turn":
        state.noninterruptible_turn_active = True
    if gate == "compacting":
        state.compacting = True

    assert not await send_preempt("notification", state=state, config=config)
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


# --- process_batch in the default message mode ---


def _notif(tmp_path, name: str, source: str = "whatsapp") -> vm.Notification:
    f = tmp_path / f"{name}.json"
    f.write_text("x")
    return vm.Notification(timestamp=dt.datetime(2025, 1, 1), source=source, type="message", body=name, file_path=str(f))


@pytest.mark.anyio
async def test_process_batch_pre_sends_first_section_only(config, state, tmp_path):
    """A mixed batch renders two sections: the first preempts via pre-send, the second queues behind it."""
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
    first, second = queue.get_nowait(), queue.get_nowait()
    assert first.pre_sent and not second.pre_sent
    [sent] = await _sent_messages(state.client)
    assert sent["priority"] == "now"
    assert first.text in sent["message"]["content"]


@pytest.mark.anyio
async def test_process_batch_while_idle_queues_without_presend(config, state, tmp_path):
    """With no turn running there is nothing to preempt: the batch queues normally."""
    from core.loops import process_batch

    state.client = MagicMock()
    state.client.query = AsyncMock()
    queue: asyncio.Queue = asyncio.Queue()

    with patch("core.loops.load_prompt", return_value=""):
        await process_batch([_notif(tmp_path, "n")], queue=queue, state=state, config=config)

    item = queue.get_nowait()
    assert not item.pre_sent
    state.client.query.assert_not_called()


@pytest.mark.anyio
async def test_process_batch_pre_send_failure_falls_back_to_plain_queueing(config, state, tmp_path):
    from core.loops import process_batch

    state.client = MagicMock()
    state.client.query = AsyncMock(side_effect=RuntimeError("transport closed"))
    state.turn = vm.TurnSignals()
    queue: asyncio.Queue = asyncio.Queue()

    with patch("core.loops.load_prompt", return_value=""):
        await process_batch([_notif(tmp_path, "n")], queue=queue, state=state, config=config)

    item = queue.get_nowait()
    assert not item.pre_sent, "a failed pre-send must degrade to a normal (re-queried) turn"


# --- the processor never interrupts in message mode ---


@pytest.mark.anyio
async def test_processor_collects_mid_turn_items_without_interrupting(config, state):
    """In the default mode a mid-turn queue item never fires the interrupt path: the running
    turn ends CLI-side (pre-sent) or completes naturally (plain item), and the item runs next."""
    from core.loops import _run_messages_with_interrupts

    queue: asyncio.Queue = asyncio.Queue()
    processed: list[tuple[str, bool]] = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_process(msg, *, state, config, is_user, pre_sent=False):
        processed.append((msg, pre_sent))
        if msg == "first":
            first_started.set()
            await release_first.wait()
        return (["OK"], state)

    with patch("core.loops.process_message", fake_process):
        task = asyncio.create_task(_run_messages_with_interrupts(vm.QueuedTurn("first", True, []), queue=queue, state=state, config=config))
        await first_started.wait()
        await queue.put(vm.QueuedTurn("second", False, [], pre_sent=True))
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None and not state.interrupt_event.is_set(), "message mode must never fire the interrupt path"
        # In production the pre-send has already ended the first turn CLI-side; the fake stands in for that.
        release_first.set()
        await task

    assert processed == [("first", False), ("second", True)], f"the pre-sent item must run next, with pre_sent forwarded: {processed}"
