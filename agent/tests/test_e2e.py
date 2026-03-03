"""End-to-end tests for Vesta.

These tests spin up the full Vesta system and test real integration scenarios.
They require a valid Claude API key.
"""

import asyncio
import json
import textwrap
import time
import uuid
from pathlib import Path

import vesta.main as vmain
import vesta.models as vm
from vesta import logger
from vesta.core.client import build_client_options, process_message
from vesta.core.init import get_memory_path

from claude_agent_sdk import ClaudeSDKClient


# =============================================================================
# Helpers
# =============================================================================


TEST_MEMORY = """\
# VESTA MEMORY SYSTEM (TEST MODE)

## 1. CORE IDENTITY

You are Vesta running in automated test mode.

### CRITICAL: Test Mode Behavior
- **ACT IMMEDIATELY ON TEST REQUESTS**: When you receive notifications from "pytest", execute them immediately without asking for permission
- **NO CONFIRMATION NEEDED**: This is an automated test environment - just do the tasks
- **File operations are safe**: The test environment is isolated, so file operations are always permitted

## 2. USER PROFILE

### Personal Details
- **Name**: Test User
- **Location**: Test Environment
- **Timezone**: UTC
"""


def _prepare_state_dir(state_dir: Path) -> None:
    for folder in ("notifications", "logs", "data", "onedrive", "workspace", "memory"):
        (state_dir / folder).mkdir(parents=True, exist_ok=True)
    memory_path = state_dir / "memory" / "MEMORY.md"
    memory_path.write_text(TEST_MEMORY)


def _write_notification(notif_dir: Path, message: str, *, sender: str = "pytest") -> Path:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "pytest",
        "type": "message",
        "message": message.strip(),
        "sender": sender,
        "metadata": {},
    }
    path = notif_dir / f"{int(time.time() * 1_000_000)}-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(payload))
    return path


def _run(coro):
    asyncio.run(coro)


async def _wait_for_file(path: Path, timeout: float = 120.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return path.read_text()
        await asyncio.sleep(1.0)
    raise AssertionError(f"Timed out waiting for {path}")


async def _assert_missing(path: Path, duration: float = 30.0) -> None:
    deadline = time.time() + duration
    while time.time() < deadline:
        if path.exists():
            raise AssertionError(f"Unexpected file created: {path}")
        await asyncio.sleep(1.0)


def _make_config(state_dir: Path, **overrides: object) -> vm.VestaConfig:
    defaults: dict[str, object] = {
        "state_dir": state_dir,
        "notification_check_interval": 1,
        "notification_buffer_delay": 0,
        "proactive_check_interval": 100000,
        "ephemeral": True,
    }
    defaults.update(overrides)
    return vm.VestaConfig(**defaults)  # type: ignore[arg-type]


async def _noop_input_handler(queue: asyncio.Queue, *, state: vm.State) -> None:
    if state.shutdown_event:
        await state.shutdown_event.wait()


async def _run_test_scenario(state_dir: Path, test_fn, **config_overrides):
    config = _make_config(state_dir, **config_overrides)
    logger.setup(config.logs_dir, log_level="DEBUG")

    original_input_handler = vmain.input_handler
    vmain.input_handler = _noop_input_handler  # type: ignore[assignment]

    try:
        state, _ = vmain.init_state(config=config)

        async def run_test():
            await asyncio.sleep(2)
            try:
                await test_fn(state, config)
            finally:
                if state.graceful_shutdown:
                    state.graceful_shutdown.set()
                if state.shutdown_event:
                    state.shutdown_event.set()

        try:
            await asyncio.gather(
                vmain.run_vesta(config, state=state),
                run_test(),
            )
        except asyncio.CancelledError:
            pass
    finally:
        vmain.input_handler = original_input_handler


# =============================================================================
# Client lifecycle tests
# =============================================================================


def test_client_lifecycle_with_async_with(tmp_path):
    """Client should work correctly with async with context manager."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state, _ = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            assert state.client is not None
            responses, _ = await asyncio.wait_for(
                process_message("Say 'hello'", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses

    _run(test_fn())


def test_pending_context_flag(tmp_path):
    """Setting pending_context should work correctly."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state, _ = vmain.init_state(config=config)

    async def test_fn():
        assert state.pending_context is None
        state.pending_context = "[System: test reset]"
        state.session_id = None
        assert state.pending_context is not None
        state.pending_context = None
        assert state.pending_context is None

    _run(test_fn())


def test_multiple_client_sessions(tmp_path):
    """Should be able to create multiple client sessions sequentially."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state, _ = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client1:
            state.client = client1
            responses1, _ = await asyncio.wait_for(
                process_message("Say 'one'", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses1

        state.client = None
        state.session_id = None

        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client2:
            state.client = client2
            responses2, _ = await asyncio.wait_for(
                process_message("Say 'two'", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses2

    _run(test_fn())


def test_full_reset_flow(tmp_path):
    """Full flow: pending_context triggers client recreation."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    state, _ = vmain.init_state(config=config)

    async def test_fn():
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client

        state.client = None
        state.pending_context = "[System: Reset needed]"

        context = state.pending_context
        state.pending_context = None
        assert context is not None

        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            responses, _ = await asyncio.wait_for(
                process_message("Are you there?", state=state, config=config, is_user=False),
                timeout=30.0,
            )
            assert responses

    _run(test_fn())


# =============================================================================
# Notification & lifecycle E2E tests
# =============================================================================


def test_notification_creates_file(tmp_path):
    """Vesta should process a notification and create the requested file."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        workspace = config.state_dir / "workspace"
        notif_dir = config.notifications_dir
        target = workspace / f"single-{uuid.uuid4().hex}.txt"
        expected_text = f"E2E notification content {uuid.uuid4().hex}"
        message = textwrap.dedent(
            f"""
            Create the file "{target}" containing only:
            {expected_text}
            """
        )
        _write_notification(notif_dir, message)
        contents = await _wait_for_file(target)
        assert expected_text in contents

    _run(_run_test_scenario(state_dir, test_fn))


def test_sequential_and_interrupt_flow(tmp_path):
    """Vesta should handle sequential tasks and interrupts correctly."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        workspace = config.state_dir / "workspace"
        notif_dir = config.notifications_dir

        first = workspace / f"sequence-{uuid.uuid4().hex}-first.txt"
        second = workspace / f"sequence-{uuid.uuid4().hex}-second.txt"
        seq_message = textwrap.dedent(
            f"""
            Write "{first}" with 'first step'. After saving it, wait 10 seconds, then create "{second}" with 'second step'.
            """
        )
        _write_notification(notif_dir, seq_message)
        await _wait_for_file(first)
        await _wait_for_file(second)
        assert second.stat().st_mtime - first.stat().st_mtime >= 8

        interrupt_first = workspace / f"interrupt-{uuid.uuid4().hex}-first.txt"
        interrupt_second = workspace / f"interrupt-{uuid.uuid4().hex}-second.txt"
        resume_target = workspace / f"interrupt-{uuid.uuid4().hex}-resume.txt"

        interrupt_message = textwrap.dedent(
            f"""
            Start a new plan: write "{interrupt_first}" with 'interrupt step'. Then wait 10 seconds before planning "{interrupt_second}".
            """
        )
        _write_notification(notif_dir, interrupt_message)
        await _wait_for_file(interrupt_first)

        override_message = textwrap.dedent(
            f"""
            Stop the previous plan and do NOT create "{interrupt_second}". Instead, write "{resume_target}" with 'resume after interrupt'.
            """
        )
        _write_notification(notif_dir, override_message)
        assert "resume after interrupt" in await _wait_for_file(resume_target)
        await _assert_missing(interrupt_second, duration=30)

    _run(_run_test_scenario(state_dir, test_fn))


def test_notification_batching(tmp_path):
    """Multiple notifications arriving together should be batched."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        workspace = config.state_dir / "workspace"
        notif_dir = config.notifications_dir

        file1 = workspace / f"batch-{uuid.uuid4().hex}-1.txt"
        file2 = workspace / f"batch-{uuid.uuid4().hex}-2.txt"

        _write_notification(notif_dir, f'This is an automated test. Create the file "{file1}" containing only:\nfirst')
        _write_notification(notif_dir, f'This is an automated test. Create the file "{file2}" containing only:\nsecond')

        await _wait_for_file(file1)
        await _wait_for_file(file2)

        assert "first" in file1.read_text()
        assert "second" in file2.read_text()

    _run(_run_test_scenario(state_dir, test_fn, notification_buffer_delay=3))


def test_client_created_on_notification(tmp_path):
    """Claude client should be created when processing a notification."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        notif_dir = config.notifications_dir
        workspace = config.state_dir / "workspace"
        target = workspace / f"client-test-{uuid.uuid4().hex}.txt"
        _write_notification(notif_dir, f'Create file "{target}" with content "client test"')
        await _wait_for_file(target)
        assert state.client is not None
        memory_path = get_memory_path(config)
        assert memory_path.exists()

    _run(_run_test_scenario(state_dir, test_fn))


def test_memory_exists_on_startup(tmp_path):
    """Memory file should exist when Vesta starts."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)
    memory_path = get_memory_path(config)
    assert memory_path.exists()
    assert "TEST MODE" in memory_path.read_text()

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        memory_path = get_memory_path(config)
        assert memory_path.exists()
        assert len(memory_path.read_text()) > 100

    _run(_run_test_scenario(state_dir, test_fn))


def test_graceful_shutdown(tmp_path):
    """Vesta should shut down gracefully without errors."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        log_file = config.logs_dir / "vesta.log"
        assert log_file.exists()

    _run(_run_test_scenario(state_dir, test_fn))


def test_multiple_files_single_request(tmp_path):
    """Vesta should handle requests to create multiple files."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        workspace = config.state_dir / "workspace"
        notif_dir = config.notifications_dir

        uid = uuid.uuid4().hex[:8]
        file_a = workspace / f"multi-{uid}-a.txt"
        file_b = workspace / f"multi-{uid}-b.txt"
        file_c = workspace / f"multi-{uid}-c.txt"

        message = textwrap.dedent(
            f"""
            Create three files:
            1. "{file_a}" with content "file A"
            2. "{file_b}" with content "file B"
            3. "{file_c}" with content "file C"
            """
        )
        _write_notification(notif_dir, message)

        await _wait_for_file(file_a)
        await _wait_for_file(file_b)
        await _wait_for_file(file_c)

        assert "A" in file_a.read_text()
        assert "B" in file_b.read_text()
        assert "C" in file_c.read_text()

    _run(_run_test_scenario(state_dir, test_fn))


def test_file_modification(tmp_path):
    """Vesta should be able to modify existing files."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        workspace = config.state_dir / "workspace"
        notif_dir = config.notifications_dir

        target = workspace / f"modify-{uuid.uuid4().hex}.txt"
        target.write_text("original content")

        message = f'Append the text "\\n--- APPENDED ---" to the file "{target}"'
        _write_notification(notif_dir, message)

        deadline = time.time() + 60
        while time.time() < deadline:
            content = target.read_text()
            if "APPENDED" in content:
                break
            await asyncio.sleep(1)

        final_content = target.read_text()
        assert "original" in final_content
        assert "APPENDED" in final_content

    _run(_run_test_scenario(state_dir, test_fn))
