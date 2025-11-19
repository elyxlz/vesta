import asyncio
import contextlib
import json
import textwrap
import time
import uuid
from pathlib import Path

import pytest

import vesta.main as vmain
import vesta.models as vm

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _prepare_state_dir(state_dir: Path) -> None:
    for folder in ("notifications", "logs", "data", "onedrive", "workspace"):
        (state_dir / folder).mkdir(parents=True, exist_ok=True)
    memory_src = PROJECT_ROOT / "MEMORY.md"
    memory_target = state_dir / "MEMORY.md"
    memory_target.write_text(memory_src.read_text() if memory_src.exists() else "Temporary memory for e2e tests.\n")


def _write_notification(notif_dir: Path, message: str) -> Path:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "pytest",
        "type": "message",
        "message": message.strip(),
        "sender": "pytest",
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


async def _start_vesta(state_dir: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[vm.State, asyncio.Task]:
    config = vm.VestaSettings(
        state_dir=str(state_dir),
        enable_whatsapp_greeting=False,
        enable_nightly_memory=False,
        notification_check_interval=1,
        notification_buffer_delay=0,
        proactive_check_interval=100000,
    )

    async def fake_input_handler(queue, *, state):
        if state.shutdown_event:
            await state.shutdown_event.wait()

    monkeypatch.setattr(vmain, "input_handler", fake_input_handler)

    vlog = vmain.vlog
    vlog.setup_logging(config.logs_dir, debug=True)

    state = await vmain.init_state(config=config)
    task = asyncio.create_task(vmain.run_vesta(config, state=state))
    await asyncio.sleep(2)
    return state, task


async def _shutdown_vesta(state: vm.State, task: asyncio.Task) -> None:
    if state.shutdown_event and not state.shutdown_event.is_set():
        state.shutdown_event.set()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(task, timeout=30)


def test_notification_creates_file(monkeypatch, tmp_path):
    async def scenario():
        state_dir = tmp_path / "state"
        _prepare_state_dir(state_dir)
        state, task = await _start_vesta(state_dir, monkeypatch)
        try:
            workspace = state_dir / "workspace"
            notif_dir = state_dir / "notifications"
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
        finally:
            await _shutdown_vesta(state, task)

    _run(scenario())


def test_sequential_and_interrupt_flow(monkeypatch, tmp_path):
    async def scenario():
        state_dir = tmp_path / "state"
        _prepare_state_dir(state_dir)
        state, task = await _start_vesta(state_dir, monkeypatch)
        try:
            workspace = state_dir / "workspace"
            notif_dir = state_dir / "notifications"

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
        finally:
            await _shutdown_vesta(state, task)

    _run(scenario())
