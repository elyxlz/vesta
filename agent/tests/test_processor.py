"""Tests for message processor: error recovery, timeout, restart, cancellation."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import ClaudeSDKError

import vesta.models as vm
from vesta.core.client import process_message
from vesta.core.loops import _is_transient, _MAX_TRANSIENT_RETRIES


async def _run_processor_test(
    tmp_path,
    *,
    message_side_effect,
    pre_state: vm.State | None = None,
    initial_queue: list[tuple[str, bool]] | None = None,
    extra_patches: dict | None = None,
):
    """Shared helper for message_processor tests."""
    from vesta.core.loops import message_processor

    config = vm.VestaConfig(root=tmp_path)
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
        "vesta.core.loops.ClaudeSDKClient": mock_client,
        "vesta.core.loops.process_message": tracking_process_message,
        "vesta.core.loops.build_client_options": MagicMock(),
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
    from vesta.main import _write_restart_reason, _read_restart_reason

    config = vm.VestaConfig(root=tmp_path)
    config.data_dir.mkdir(parents=True, exist_ok=True)

    _write_restart_reason(config, "nightly — conversation history reset, dreamer ran")
    assert _read_restart_reason(config) == "nightly — conversation history reset, dreamer ran"
    # File is consumed after reading
    assert _read_restart_reason(config) == "crash — restarted after unexpected exit"


@pytest.mark.anyio
async def test_client_cleared_on_cancellation(tmp_path):
    from vesta.core.loops import message_processor

    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("vesta.core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("vesta.core.loops.build_client_options", return_value=MagicMock()),
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
    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        if len(converse_calls) == 1:
            return ["something \u2014 with an em dash"]
        return ["corrected response"]

    with patch("vesta.core.client.converse", side_effect=mock_converse):
        responses, _ = await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 2
    assert "em dash" in converse_calls[1].lower()
    assert responses == ["something \u2014 with an em dash"]


@pytest.mark.anyio
async def test_process_message_no_correction_without_dashes(tmp_path):
    """process_message should not send a correction when no dashes are present."""
    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        return ["clean response, no dashes here"]

    with patch("vesta.core.client.converse", side_effect=mock_converse):
        await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 1


@pytest.mark.anyio
async def test_process_message_no_correction_on_empty_response(tmp_path):
    """process_message should not send a correction when there are no responses."""
    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        return []

    with patch("vesta.core.client.converse", side_effect=mock_converse):
        await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 1


# --- Transient error handling ---


@pytest.mark.parametrize(
    "msg",
    ["HTTP 500 error", "502 bad gateway", "503 service unavailable", "529 overloaded", "overloaded_error", "internal_error"],
)
def test_is_transient_matches(msg):
    assert _is_transient(RuntimeError(msg))


@pytest.mark.parametrize("msg", ["connection refused", "timeout", "invalid request", "401 unauthorized"])
def test_is_transient_no_match(msg):
    assert not _is_transient(RuntimeError(msg))


@pytest.mark.anyio
async def test_transient_error_no_restart(tmp_path):
    from vesta.core.loops import _process_message_safely

    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()

    async def side_effect(msg, *, state, config, is_user):
        raise ClaudeSDKError("HTTP 500 Internal Server Error")

    with patch("vesta.core.loops.process_message", side_effect=side_effect):
        await _process_message_safely("hello", is_user=True, state=state, config=config)

    assert not state.graceful_shutdown.is_set()
    assert state.api_failures == 1


@pytest.mark.anyio
async def test_transient_error_resets_on_success(tmp_path):
    from vesta.core.loops import _process_message_safely

    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.api_failures = 2

    async def side_effect(msg, *, state, config, is_user):
        return ([], state)

    with patch("vesta.core.loops.process_message", side_effect=side_effect):
        await _process_message_safely("hello", is_user=True, state=state, config=config)

    assert state.api_failures == 0
    assert not state.graceful_shutdown.is_set()


@pytest.mark.anyio
async def test_retry_loop_recovers(tmp_path):
    from vesta.core.loops import _process_message_safely

    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.api_failures = _MAX_TRANSIENT_RETRIES - 1

    call_count = 0

    async def side_effect(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ClaudeSDKError("HTTP 503 Service Unavailable")
        return ([], state)

    with (
        patch("vesta.core.loops.process_message", side_effect=side_effect),
        patch("vesta.core.loops._RETRY_INTERVAL", 0.01),
    ):
        await _process_message_safely("hello", is_user=True, state=state, config=config)

    assert not state.graceful_shutdown.is_set()
    assert state.api_failures == 0
    assert call_count == 2


@pytest.mark.anyio
async def test_retry_loop_exits_on_shutdown(tmp_path):
    from vesta.core.loops import _process_message_safely

    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.api_failures = _MAX_TRANSIENT_RETRIES - 1

    call_count = 0

    async def side_effect(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            state.shutdown_event.set()
        raise ClaudeSDKError("HTTP 503 Service Unavailable")

    with (
        patch("vesta.core.loops.process_message", side_effect=side_effect),
        patch("vesta.core.loops._RETRY_INTERVAL", 0.01),
    ):
        await _process_message_safely("hello", is_user=True, state=state, config=config)

    assert not state.graceful_shutdown.is_set()
    assert call_count == 2


@pytest.mark.anyio
async def test_retry_loop_non_transient_triggers_restart(tmp_path):
    from vesta.core.loops import _process_message_safely

    config = vm.VestaConfig(root=tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.api_failures = _MAX_TRANSIENT_RETRIES - 1

    call_count = 0

    async def side_effect(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ClaudeSDKError("HTTP 503 Service Unavailable")
        raise RuntimeError("Unexpected buffer overflow")

    with (
        patch("vesta.core.loops.process_message", side_effect=side_effect),
        patch("vesta.core.loops._RETRY_INTERVAL", 0.01),
    ):
        await _process_message_safely("hello", is_user=True, state=state, config=config)

    assert state.graceful_shutdown.is_set()
    assert "buffer overflow" in state.restart_reason
    assert call_count == 2
