"""End-to-end tests for Vesta.

These tests spin up the full Vesta system and test real integration scenarios.
"""

import asyncio
import json
import textwrap
import time
import uuid
from pathlib import Path


import vesta.main as vmain
import vesta.models as vm
import vesta.logging_setup as vlog
from vesta.agents import AGENT_NAMES, get_memory_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# =============================================================================
# Test Helpers
# =============================================================================


def _prepare_state_dir(state_dir: Path) -> None:
    """Create required directories and memory file for test."""
    for folder in ("notifications", "logs", "data", "onedrive", "workspace"):
        (state_dir / folder).mkdir(parents=True, exist_ok=True)
    memory_src = PROJECT_ROOT / "MEMORY.md"
    memory_target = state_dir / "MEMORY.md"
    memory_target.write_text(memory_src.read_text() if memory_src.exists() else "Temporary memory for e2e tests.\n")


def _write_notification(notif_dir: Path, message: str, *, sender: str = "pytest") -> Path:
    """Write a notification JSON file."""
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
    """Run an async test scenario."""
    asyncio.run(coro)


async def _wait_for_file(path: Path, timeout: float = 120.0) -> str:
    """Wait for a file to exist and return its contents."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            return path.read_text()
        await asyncio.sleep(1.0)
    raise AssertionError(f"Timed out waiting for {path}")


async def _assert_missing(path: Path, duration: float = 30.0) -> None:
    """Assert that a file does NOT get created within duration."""
    deadline = time.time() + duration
    while time.time() < deadline:
        if path.exists():
            raise AssertionError(f"Unexpected file created: {path}")
        await asyncio.sleep(1.0)


def _make_config(state_dir: Path, **overrides) -> vm.VestaSettings:
    """Create a test config with sensible defaults."""
    defaults = {
        "state_dir": state_dir,
        "microsoft_mcp_client_id": "test-client",
        "enable_whatsapp_greeting": False,
        "enable_nightly_memory": False,
        "notification_check_interval": 1,
        "notification_buffer_delay": 0,
        "proactive_check_interval": 100000,
        "ephemeral": True,
    }
    defaults.update(overrides)
    return vm.VestaSettings(**defaults)


async def _noop_input_handler(queue: asyncio.Queue, *, state: vm.State) -> None:
    """Replacement input handler that just waits for shutdown."""
    if state.shutdown_event:
        await state.shutdown_event.wait()


async def _run_test_scenario(state_dir: Path, test_fn, **config_overrides):
    """Run a test scenario with full Vesta lifecycle in same task context."""
    config = _make_config(state_dir, **config_overrides)
    vlog.setup_logging(config.logs_dir, debug=True)

    original_input_handler = vmain.input_handler
    vmain.input_handler = _noop_input_handler

    try:
        state = await vmain.init_state(config=config)

        async def run_test():
            await asyncio.sleep(2)
            try:
                await test_fn(state, config)
            finally:
                if state.shutdown_event:
                    state.shutdown_event.set()

        try:
            await asyncio.gather(
                vmain.run_vesta(config, state=state),
                run_test(),
            )
        except asyncio.CancelledError:
            pass  # Expected during shutdown
    finally:
        vmain.input_handler = original_input_handler


# =============================================================================
# E2E Tests
# =============================================================================


def test_notification_creates_file(tmp_path):
    """Vesta should process a notification and create the requested file."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaSettings):
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

    async def test_fn(state: vm.State, config: vm.VestaSettings):
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

    async def test_fn(state: vm.State, config: vm.VestaSettings):
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


def test_subagents_available_on_startup(tmp_path):
    """Sub-agents should be configured and available when Vesta starts."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaSettings):
        assert state.client is not None

        for agent_name in AGENT_NAMES:
            memory_path = get_memory_path(config, agent_name=agent_name)
            assert memory_path.exists(), f"Memory for {agent_name} should be initialized"

    _run(_run_test_scenario(state_dir, test_fn))


def test_memory_initialized_from_templates(tmp_path):
    """Memory files should be initialized from templates on first run."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)
    config = _make_config(state_dir)

    # Verify no memory files exist before startup
    for agent_name in AGENT_NAMES:
        memory_path = get_memory_path(config, agent_name=agent_name)
        assert not memory_path.exists()

    async def test_fn(state: vm.State, config: vm.VestaSettings):
        for agent_name in AGENT_NAMES:
            memory_path = get_memory_path(config, agent_name=agent_name)
            assert memory_path.exists(), f"Memory for {agent_name} should exist"
            content = memory_path.read_text()
            assert len(content) > 100, f"Memory for {agent_name} should have content"

    _run(_run_test_scenario(state_dir, test_fn))


def test_graceful_shutdown(tmp_path):
    """Vesta should shut down gracefully without errors."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaSettings):
        # Just verify startup succeeded, then let shutdown happen
        assert state.client is not None
        log_file = config.logs_dir / "vesta.log"
        assert log_file.exists()

    _run(_run_test_scenario(state_dir, test_fn))


def test_multiple_files_single_request(tmp_path):
    """Vesta should handle requests to create multiple files."""
    state_dir = tmp_path / "state"
    _prepare_state_dir(state_dir)

    async def test_fn(state: vm.State, config: vm.VestaSettings):
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

    async def test_fn(state: vm.State, config: vm.VestaSettings):
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
