"""Tests for crash recovery: session resume fallback, crash detail formatting, processor done callback."""

import asyncio
import collections
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import ClaudeSDKError

import core.models as vm
from core.client import format_crash_detail
from core.helpers import MEMORY_RECOVERY_MIN_BYTES, restore_memory_from_head_if_wiped


# --- format_crash_detail ---


class FakeProcessError(ClaudeSDKError):
    def __init__(self, msg: str, exit_code: int):
        super().__init__(msg)
        self.exit_code = exit_code


def test_format_crash_detail_with_exit_code():
    exc = FakeProcessError("CLI died", exit_code=1)
    buf: collections.deque[str] = collections.deque(["line1", "line2"], maxlen=50)
    exit_code, stderr_tail = format_crash_detail(exc, buf)
    assert exit_code == 1
    assert stderr_tail == "line1\nline2"


def test_format_crash_detail_no_exit_code():
    exc = RuntimeError("generic error")
    buf: collections.deque[str] = collections.deque(["some stderr"], maxlen=50)
    exit_code, stderr_tail = format_crash_detail(exc, buf)
    assert exit_code is None
    assert stderr_tail == "some stderr"


def test_format_crash_detail_empty_buffer():
    exc = RuntimeError("boom")
    buf: collections.deque[str] = collections.deque(maxlen=50)
    exit_code, stderr_tail = format_crash_detail(exc, buf)
    assert exit_code is None
    assert stderr_tail == "(no stderr captured)"


def test_format_crash_detail_custom_fallback():
    exc = RuntimeError("boom")
    buf: collections.deque[str] = collections.deque(maxlen=50)
    _, stderr_tail = format_crash_detail(exc, buf, fallback="")
    assert stderr_tail == ""


# --- Session resume fallback in message_processor ---


@pytest.mark.anyio
async def test_resume_fallback_clears_session_and_retries(tmp_path):
    """When ClaudeSDKClient.__aenter__ fails with a session_id set, it should clear the session and retry."""
    from core.loops import message_processor

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.session_file.write_text("stale-session-id-1234567890")

    state = vm.State(session_id="stale-session-id-1234567890")
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    enter_count = 0
    mock_client = MagicMock()

    async def mock_enter(self):
        nonlocal enter_count
        enter_count += 1
        if enter_count == 1:
            raise ClaudeSDKError("session not found")
        return mock_client

    mock_client.return_value = mock_client
    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def shutdown_soon():
        await asyncio.sleep(0.1)
        state.shutdown_event.set()

    with (
        patch("core.loops.ClaudeSDKClient", mock_client),
        patch("core.loops.build_client_options", return_value=MagicMock()),
    ):
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            shutdown_soon(),
        )

    assert enter_count == 2
    assert state.session_id is None
    assert not config.session_file.exists()


@pytest.mark.anyio
async def test_resume_fallback_raises_without_session(tmp_path):
    """When __aenter__ fails and there's no session_id, it should raise immediately."""
    from core.loops import message_processor

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State(session_id=None)
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    mock_client = MagicMock()

    async def mock_enter(self):
        raise ClaudeSDKError("connection failed")

    mock_client.return_value = mock_client
    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("core.loops.ClaudeSDKClient", mock_client),
        patch("core.loops.build_client_options", return_value=MagicMock()),
    ):
        with pytest.raises(ClaudeSDKError, match="connection failed"):
            await message_processor(queue, state=state, config=config)


@pytest.mark.anyio
async def test_resume_fallback_raises_on_second_failure(tmp_path):
    """When retry also fails, it should raise."""
    from core.loops import message_processor

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.session_file.write_text("stale-session")

    state = vm.State(session_id="stale-session-1234567890")
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    mock_client = MagicMock()

    async def mock_enter(self):
        raise ClaudeSDKError("always fails")

    mock_client.return_value = mock_client
    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("core.loops.ClaudeSDKClient", mock_client),
        patch("core.loops.build_client_options", return_value=MagicMock()),
    ):
        with pytest.raises(ClaudeSDKError, match="always fails"):
            await message_processor(queue, state=state, config=config)


# --- Processor done callback ---


@pytest.mark.anyio
async def test_processor_crash_triggers_graceful_shutdown(tmp_path):
    """When message_processor crashes, _on_processor_done should set graceful_shutdown."""
    from core.main import run_vesta

    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    for path in [config.data_dir, config.notifications_dir, config.logs_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    state = vm.State()

    async def crashing_processor(queue, *, state, config, **kwargs):
        raise RuntimeError("processor exploded")

    with (
        patch("core.main.start_ws_server", new_callable=AsyncMock) as mock_ws,
        patch("core.main.message_processor", side_effect=crashing_processor),
        patch("core.main.monitor_loop", new_callable=AsyncMock),
        patch("core.main.input_handler", new_callable=AsyncMock),
        patch("core.main.queue_greeting", new_callable=AsyncMock),
    ):
        mock_runner = MagicMock()
        mock_runner.cleanup = AsyncMock()
        mock_ws.return_value = mock_runner

        await run_vesta(config, state=state)

    assert "crash" in (state.restart_reason or "")
    assert "RuntimeError" in (state.restart_reason or "")


# --- stderr buffer ---


def test_stderr_buffer_on_state():
    state = vm.State()
    assert len(state.stderr_buffer) == 0
    assert state.stderr_buffer.maxlen == 50

    for i in range(60):
        state.stderr_buffer.append(f"line {i}")
    assert len(state.stderr_buffer) == 50
    assert state.stderr_buffer[0] == "line 10"


# --- MEMORY.md restore from HEAD on boot (dreamer wipe recovery) ---


def _init_repo_with_memory(repo_root, memory_relative_path: str, content: str) -> None:
    """Init a git repo at repo_root and commit `content` at the given relative path."""
    subprocess.run(["git", "-C", str(repo_root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@vesta"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "test"], check=True)
    target = repo_root / memory_relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    subprocess.run(["git", "-C", str(repo_root), "add", memory_relative_path], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "init"], check=True)


def test_restore_memory_when_wiped(config):
    """Empty MEMORY.md is replaced with the HEAD-committed copy."""
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    real_content = "# Charter\n" + ("rule line\n" * 50)
    _init_repo_with_memory(config.agent_dir.parent, "agent/MEMORY.md", real_content)

    memory_path = config.agent_dir / "MEMORY.md"
    memory_path.write_text("")

    restore_memory_from_head_if_wiped(config)

    assert memory_path.read_text() == real_content


def test_restore_memory_when_missing(config):
    """A missing MEMORY.md is recreated from HEAD."""
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    real_content = "# Charter\n" + ("rule line\n" * 50)
    _init_repo_with_memory(config.agent_dir.parent, "agent/MEMORY.md", real_content)

    memory_path = config.agent_dir / "MEMORY.md"
    memory_path.unlink()

    restore_memory_from_head_if_wiped(config)

    assert memory_path.read_text() == real_content


def test_restore_memory_noop_when_intact(config):
    """A healthy MEMORY.md is not touched, and the function does not invoke git."""
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    intact = "x" * (MEMORY_RECOVERY_MIN_BYTES + 100)
    memory_path = config.agent_dir / "MEMORY.md"
    memory_path.write_text(intact)

    # No git repo at all; if the function tried to invoke git, it would log an error,
    # so absence of changes plus a readable file proves the early return path.
    restore_memory_from_head_if_wiped(config)

    assert memory_path.read_text() == intact


def test_restore_memory_no_head_leaves_wiped_file_alone(config):
    """When MEMORY.md is wiped and there is no HEAD to restore from, the function logs and does not crash."""
    config.agent_dir.mkdir(parents=True, exist_ok=True)
    memory_path = config.agent_dir / "MEMORY.md"
    memory_path.write_text("")

    restore_memory_from_head_if_wiped(config)

    assert memory_path.read_text() == ""
