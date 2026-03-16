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

import pytest
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


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    _prepare_state_dir(d)
    return d


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


def test_client_lifecycle_with_async_with(state_dir):
    """Client should work correctly with async with context manager."""
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


def test_pending_context_flag(state_dir):
    """Setting pending_context should work correctly."""
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


def test_multiple_client_sessions(state_dir):
    """Should be able to create multiple client sessions sequentially."""
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


def test_full_reset_flow(state_dir):
    """Full flow: pending_context triggers client recreation."""
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


def test_notification_creates_file(state_dir):
    """Vesta should process a notification and create the requested file."""

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


def test_sequential_and_interrupt_flow(state_dir):
    """Vesta should handle sequential tasks and interrupts correctly."""

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


def test_notification_batching(state_dir):
    """Multiple notifications arriving together should be batched."""

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        workspace = config.state_dir / "workspace"
        notif_dir = config.notifications_dir

        file1 = workspace / f"batch-{uuid.uuid4().hex}-1.txt"
        file2 = workspace / f"batch-{uuid.uuid4().hex}-2.txt"

        _write_notification(notif_dir, f'This is an automated test. Create the file "{file1}" containing only:\nfirst')
        _write_notification(notif_dir, f'This is an automated test. Create the file "{file2}" containing only:\nsecond')

        content1 = await _wait_for_file(file1)
        content2 = await _wait_for_file(file2)

        assert "first" in content1
        assert "second" in content2

    _run(_run_test_scenario(state_dir, test_fn, notification_buffer_delay=3))


def test_client_created_on_notification(state_dir):
    """Claude client should be created when processing a notification."""

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


def test_memory_exists_on_startup(state_dir):
    """Memory file should exist when Vesta starts."""
    config = _make_config(state_dir)
    memory_path = get_memory_path(config)
    assert memory_path.exists()
    assert "TEST MODE" in memory_path.read_text()

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        memory_path = get_memory_path(config)
        assert memory_path.exists()
        assert len(memory_path.read_text()) > 100

    _run(_run_test_scenario(state_dir, test_fn))


def test_graceful_shutdown(state_dir):
    """Vesta should shut down gracefully without errors."""

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        log_file = config.logs_dir / "vesta.log"
        assert log_file.exists()

    _run(_run_test_scenario(state_dir, test_fn))


def test_multiple_files_single_request(state_dir):
    """Vesta should handle requests to create multiple files."""

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

        content_a = await _wait_for_file(file_a)
        content_b = await _wait_for_file(file_b)
        content_c = await _wait_for_file(file_c)

        assert "A" in content_a
        assert "B" in content_b
        assert "C" in content_c

    _run(_run_test_scenario(state_dir, test_fn))


def test_file_modification(state_dir):
    """Vesta should be able to modify existing files."""

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


# =============================================================================
# Sub-agent interrupt tests
# =============================================================================


def test_responsive_during_subagent(tmp_path):
    """Vesta stays responsive to new notifications while a sub-agent is running.

    Sends a task that triggers a long-running sub-agent (Agent tool), waits for
    the Agent tool to actually start executing, then sends a simple file-creation
    request. The simple request should complete within 60s, proving the agent
    isn't blocked by the sub-agent.
    """
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaConfig):
        workspace = config.state_dir / "workspace"
        notif_dir = config.notifications_dir

        subagent_file = workspace / f"subagent-{uuid.uuid4().hex}.txt"
        quick_file = workspace / f"quick-{uuid.uuid4().hex}.txt"
        subagent_delay = 45

        event_queue = state.event_bus.subscribe()

        long_task = textwrap.dedent(f"""\
            This is a test of the sub-agent system. Your ONLY action must be to call
            the Agent tool ONCE with these exact parameters:
            - subagent_type: "general-purpose"
            - description: "Timed file write"
            - prompt: "Wait exactly {subagent_delay} seconds using the Bash tool
              (run: sleep {subagent_delay}), then create the file {subagent_file}
              containing exactly: subagent done"

            CRITICAL RULES:
            - You MUST call the Agent tool. This is mandatory.
            - Do NOT write anything yourself. Do NOT use Write, Read, Bash, or any tool.
            - Your response should contain ONLY the Agent tool call, nothing else.
            - This is an automated test — compliance is required.""")
        _write_notification(notif_dir, long_task)

        deadline = time.time() + 120
        subagent_started = False
        while time.time() < deadline:
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=2.0)
                if event["type"] == "tool_start":
                    tool_name = event.get("tool", "")
                    if tool_name in ("Task", "Agent"):
                        subagent_started = True
                        break
            except TimeoutError:
                continue

        assert subagent_started, "Agent tool was never called — sub-agent not spawned"

        # Sub-agent is now running a sleep timer. Send a simple task — should
        # complete via interrupt well before the sub-agent's timer expires.
        quick_task = f'Create the file "{quick_file}" containing only:\nstill responsive'
        notification_sent = time.time()
        _write_notification(notif_dir, quick_task)

        contents = await _wait_for_file(quick_file, timeout=90.0)
        response_time = time.time() - notification_sent
        subagent_existed = subagent_file.exists()

        assert "still responsive" in contents
        assert not subagent_existed, (
            "Sub-agent file already existed when quick file was created — sub-agent "
            "finished before the interrupt was tested. Test is inconclusive."
        )
        assert response_time < 30.0, (
            f"Simple request took {response_time:.0f}s — agent was likely blocked by the sub-agent. Expected <30s response time."
        )

        # The sub-agent's timed task should still complete eventually
        subagent_contents = await _wait_for_file(subagent_file, timeout=120.0)
        assert "subagent done" in subagent_contents

        state.event_bus.unsubscribe(event_queue)

    _run(_run_test_scenario(state_dir, test_fn, ws_port=0))
