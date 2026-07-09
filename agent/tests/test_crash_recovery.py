"""Tests for crash recovery: session resume fallback, crash detail formatting, processor done callback."""

import asyncio
import collections
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import ClaudeSDKError

import core.models as vm
import core.config as cfg
from conftest import idle_message_stream
from core.diagnostics import format_crash_detail
from wait_util import wait_for_condition


# --- format_crash_detail ---


class FakeProcessError(ClaudeSDKError):
    def __init__(self, msg: str, exit_code: int):
        super().__init__(msg)
        self.exit_code = exit_code


@pytest.mark.parametrize(
    "exc,lines,kwargs,expected_exit,expected_tail",
    [
        (FakeProcessError("CLI died", exit_code=1), ["line1", "line2"], {}, 1, "line1\nline2"),
        (RuntimeError("generic error"), ["some stderr"], {}, None, "some stderr"),
        (RuntimeError("boom"), [], {}, None, "(no stderr captured)"),  # empty buffer -> default fallback
        (RuntimeError("boom"), [], {"fallback": ""}, None, ""),  # custom fallback overrides
    ],
)
def test_format_crash_detail(exc, lines, kwargs, expected_exit, expected_tail):
    buf: collections.deque[str] = collections.deque(lines, maxlen=50)
    exit_code, stderr_tail = format_crash_detail(exc, buf, **kwargs)
    assert exit_code == expected_exit
    assert stderr_tail == expected_tail


# --- Session resume fallback in message_processor ---


def _mock_client(enter):
    """Build a ClaudeSDKClient stand-in whose async __aenter__ runs `enter`."""
    client = MagicMock()
    client.return_value = client
    client.receive_messages = idle_message_stream
    client.__aenter__ = enter
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _processor_config_state(tmp_path, session_id=None):
    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    # These tests exercise the client-session/resume path, which message_processor runs only for an
    # authenticated provider (it idles otherwise).
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    state.persisted.session_id = session_id
    state.shutdown_event = asyncio.Event()
    return config, state


@pytest.mark.anyio
async def test_resume_fallback_clears_session_and_retries(tmp_path):
    """When ClaudeSDKClient.__aenter__ fails with a session_id set, it should clear the session and retry."""
    from core import state_store
    from core.loops import message_processor

    config, state = _processor_config_state(tmp_path, session_id="stale-session-id-1234567890")
    state_store.save_state(state.persisted, config)
    queue: asyncio.Queue[vm.QueuedTurn] = asyncio.Queue()

    enter_count = 0

    async def mock_enter(self):
        nonlocal enter_count
        enter_count += 1
        if enter_count == 1:
            raise ClaudeSDKError("session not found")
        return mock_client

    mock_client = _mock_client(mock_enter)

    async def shutdown_after_retry():
        await wait_for_condition(lambda: enter_count >= 2, message="client __aenter__ retry never happened")
        state.shutdown_event.set()

    with (
        patch("core.client.ClaudeSDKClient", mock_client),
        patch("core.client.build_client_options", return_value=MagicMock()),
    ):
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            shutdown_after_retry(),
        )

    assert enter_count == 2
    assert state.persisted.session_id is None
    assert state_store.load_state(config).session_id is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "session_id,error",
    [
        (None, "connection failed"),  # no session: __aenter__ failure raises immediately
        ("stale-session-1234567890", "always fails"),  # session set but the retry also fails
    ],
)
async def test_resume_fallback_raises_when_enter_always_fails(tmp_path, session_id, error):
    from core.loops import message_processor

    config, state = _processor_config_state(tmp_path, session_id=session_id)
    queue: asyncio.Queue[vm.QueuedTurn] = asyncio.Queue()

    async def mock_enter(self):
        raise ClaudeSDKError(error)

    with (
        patch("core.client.ClaudeSDKClient", _mock_client(mock_enter)),
        patch("core.client.build_client_options", return_value=MagicMock()),
    ):
        with pytest.raises(ClaudeSDKError, match=error):
            await message_processor(queue, state=state, config=config)


# --- Processor done callback ---


@pytest.mark.anyio
async def test_processor_crash_triggers_graceful_shutdown(tmp_path):
    """When message_processor crashes, _on_processor_done should set graceful_shutdown."""
    from core.main import run_vesta

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    for path in [config.data_dir, config.notifications_dir, config.logs_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    state = vm.State()

    async def crashing_processor(queue, *, state, config, **kwargs):
        raise RuntimeError("processor exploded")

    with (
        patch("core.main.start_ws_server", new_callable=AsyncMock) as mock_ws,
        patch("core.main.message_processor", side_effect=crashing_processor),
        patch("core.main.monitor_loop", new_callable=AsyncMock),
        patch("core.main.collect_boot_turns", return_value=[]),
    ):
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_ws.return_value = mock_runner

        crashed = await run_vesta(config, state=state)

    reason = state.persisted.last_restart_reason or ""
    assert "crash" in reason
    assert "RuntimeError" in reason
    # run_vesta reports the crash so the entry point exits non-zero and Docker's on-failure
    # policy restarts the container.
    assert crashed is True


# --- stderr buffer ---


def test_stderr_buffer_on_state():
    state = vm.State()
    assert len(state.stderr_buffer) == 0
    assert state.stderr_buffer.maxlen == 50

    for i in range(60):
        state.stderr_buffer.append(f"line {i}")
    assert len(state.stderr_buffer) == 50
    assert state.stderr_buffer[0] == "line 10"
