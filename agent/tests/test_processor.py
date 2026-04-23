"""Tests for message processor: error recovery, timeout, restart, cancellation."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import core.models as vm
from core.client import process_message


async def _run_processor_test(
    tmp_path,
    *,
    message_side_effect,
    pre_state: vm.State | None = None,
    initial_queue: list[tuple[str, bool]] | None = None,
    extra_patches: dict | None = None,
):
    """Shared helper for message_processor tests."""
    from core.loops import message_processor

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = pre_state or vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    for item in initial_queue or []:
        await queue.put(item)

    session_count = 0
    processed_messages: list[str] = []

    original_side_effect = message_side_effect

    async def tracking_process_message(msg, *, state, config, is_user):
        processed_messages.append(msg)
        return await original_side_effect(msg, state=state, config=config, is_user=is_user)

    mock_client = MagicMock()
    mock_client.return_value = mock_client

    async def mock_enter(self):
        nonlocal session_count
        session_count += 1
        return mock_client

    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def shutdown_timer():
        await asyncio.sleep(0.15)
        assert state.shutdown_event is not None
        state.shutdown_event.set()

    patches = {
        "core.loops.ClaudeSDKClient": mock_client,
        "core.loops.process_message": tracking_process_message,
        "core.loops.build_client_options": MagicMock(),
    }
    if extra_patches:
        patches.update(extra_patches)

    ctx_managers = [patch(k, v if not callable(v) or isinstance(v, MagicMock) else v) for k, v in patches.items()]
    with contextlib.ExitStack() as stack:
        for cm in ctx_managers:
            stack.enter_context(cm)
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            shutdown_timer(),
        )

    return state, session_count, processed_messages


@pytest.mark.anyio
async def test_restarts_on_error(tmp_path):
    async def side_effect(msg, *, state, config, is_user):
        raise RuntimeError("Simulated SDK buffer overflow")

    state, session_count, messages = await _run_processor_test(
        tmp_path, message_side_effect=side_effect, initial_queue=[("first message - will fail", True)]
    )
    assert state.graceful_shutdown.is_set()
    assert state.restart_reason == "error — Simulated SDK buffer overflow"


@pytest.mark.anyio
async def test_restarts_on_timeout(tmp_path):
    async def side_effect(msg, *, state, config, is_user):
        raise TimeoutError()

    state, session_count, messages = await _run_processor_test(
        tmp_path, message_side_effect=side_effect, initial_queue=[("slow request", True)]
    )
    assert state.graceful_shutdown.is_set()
    assert state.restart_reason == "error — Response timed out"


def test_restart_reason_round_trip(tmp_path):
    from core.main import _write_restart_reason, _read_restart_reason

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    _write_restart_reason(config, "nightly — conversation history reset, dreamer ran")
    assert _read_restart_reason(config) == "nightly — conversation history reset, dreamer ran"
    # File is consumed after reading
    assert _read_restart_reason(config) == "crash — restarted after unexpected exit"


@pytest.mark.anyio
async def test_client_cleared_on_cancellation(tmp_path):
    from core.loops import message_processor

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("core.loops.build_client_options", return_value=MagicMock()),
    ):
        task = asyncio.create_task(message_processor(queue, state=state, config=config))
        await asyncio.sleep(0.05)
        assert state.client is mock_client

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert state.client is None


# --- Em/en dash correction in process_message ---


@pytest.mark.anyio
async def test_process_message_sends_correction_on_em_dash(tmp_path):
    """process_message should call converse a second time when an em dash is detected."""
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        if len(converse_calls) == 1:
            return ["something \u2014 with an em dash"]
        return ["corrected response"]

    with patch("core.client.converse", side_effect=mock_converse):
        responses, _ = await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 2
    assert "em dash" in converse_calls[1].lower()
    assert responses == ["something \u2014 with an em dash"]


@pytest.mark.anyio
async def test_process_message_no_correction_without_dashes(tmp_path):
    """process_message should not send a correction when no dashes are present."""
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        return ["clean response, no dashes here"]

    with patch("core.client.converse", side_effect=mock_converse):
        await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 1


@pytest.mark.anyio
async def test_process_message_no_correction_on_empty_response(tmp_path):
    """process_message should not send a correction when there are no responses."""
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        return []

    with patch("core.client.converse", side_effect=mock_converse):
        await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 1


@pytest.mark.anyio
async def test_cancellation_triggers_restart(tmp_path):
    """If process_message raises CancelledError, restart_reason + graceful_shutdown must be set.

    Regression test for a silent-death bug: CancelledError used to propagate uncaught through
    _process_message_safely, bypassing the restart trigger and leaving the agent wedged until
    backup SIGTERM hours later.
    """
    from core.loops import _process_message_safely

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()

    async def cancel_side_effect(msg, *, state, config, is_user):
        raise asyncio.CancelledError

    with patch("core.loops.process_message", side_effect=cancel_side_effect):
        with pytest.raises(asyncio.CancelledError):
            await _process_message_safely("msg", is_user=True, state=state, config=config)

    assert state.graceful_shutdown.is_set()
    assert state.restart_reason == "error — processing cancelled"


@pytest.mark.anyio
async def test_handle_processor_done_silent_cancel_triggers_restart():
    """Regression: a cancelled processor task used to return silently, leaving the agent wedged.
    Now it must log + set restart_reason + set graceful_shutdown."""
    from core.main import handle_processor_done

    state = vm.State()

    async def cancellable():
        await asyncio.sleep(10)

    task = asyncio.create_task(cancellable())
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    handle_processor_done(task, state=state)

    assert state.graceful_shutdown.is_set()
    assert state.restart_reason == "crash — processor cancelled unexpectedly"


@pytest.mark.anyio
async def test_handle_processor_done_exception_triggers_restart():
    """A crashed processor task should log the exception and set restart_reason."""
    from core.main import handle_processor_done

    state = vm.State()

    async def crasher():
        raise RuntimeError("simulated crash")

    task = asyncio.create_task(crasher())
    with contextlib.suppress(RuntimeError):
        await task

    handle_processor_done(task, state=state)

    assert state.graceful_shutdown.is_set()
    assert state.restart_reason is not None
    assert "RuntimeError" in state.restart_reason


@pytest.mark.anyio
async def test_handle_processor_done_silent_exit_triggers_restart():
    """A processor task that returns without error or cancellation should still trigger restart."""
    from core.main import handle_processor_done

    state = vm.State()

    async def silent():
        return None

    task = asyncio.create_task(silent())
    await task

    handle_processor_done(task, state=state)

    assert state.graceful_shutdown.is_set()
    assert state.restart_reason == "crash — processor exited silently"


@pytest.mark.anyio
async def test_handle_processor_done_noop_during_shutdown():
    """If shutdown was already initiated, the callback must not override the restart_reason."""
    from core.main import handle_processor_done

    state = vm.State()
    state.graceful_shutdown.set()
    state.restart_reason = "nightly — dreamer ran, session cleared for fresh context"

    async def silent():
        return None

    task = asyncio.create_task(silent())
    await task

    handle_processor_done(task, state=state)

    assert state.restart_reason == "nightly — dreamer ran, session cleared for fresh context"


@pytest.mark.anyio
async def test_log_context_usage_timeout(tmp_path):
    """If get_context_usage hangs, _log_context_usage must time out and not raise."""
    from core.client import _log_context_usage

    state = vm.State()
    mock_client = MagicMock()

    async def hang_forever():
        await asyncio.sleep(10)
        return {"percentage": 0, "totalTokens": 0, "maxTokens": 0}

    mock_client.get_context_usage = hang_forever
    state.client = mock_client

    with patch("core.client._CONTEXT_USAGE_TIMEOUT_S", 0.05):
        await asyncio.wait_for(_log_context_usage(state), timeout=1.0)
