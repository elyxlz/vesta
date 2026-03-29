"""Unit tests for Vesta core modules."""

import asyncio
import contextlib
import datetime as dt
import typing as tp
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import vesta.models as vm
from claude_agent_sdk import HookContext
from claude_agent_sdk.types import SubagentStartHookInput
from vesta.core.client import _format_tool_call, _parse_agent_input, _tool_summary, _subagent_hook
from vesta.core.history import format_results, history_get_range, history_save, history_search, open_history
from vesta.events import EventBus, SubagentStartEvent, SubagentStopEvent
from vesta.core.init import get_memory_path


def _make_config(tmp_path: Path) -> vm.VestaConfig:
    return vm.VestaConfig(root=tmp_path)


# --- Config & init ---


def test_config_paths_under_root(tmp_path):
    config = _make_config(tmp_path)
    assert config.notifications_dir.is_relative_to(tmp_path)
    assert config.data_dir.is_relative_to(tmp_path)
    assert config.logs_dir.is_relative_to(tmp_path)
    assert config.skills_dir.is_relative_to(config.root)


def test_config_default_values():
    config = vm.VestaConfig()
    assert config.notification_check_interval > 0
    assert config.response_timeout > 0


def test_memory_paths(tmp_path):
    config = _make_config(tmp_path)
    assert get_memory_path(config) == config.root / "MEMORY.md"
    assert config.skills_dir == config.root / "skills"


# --- Formatting ---


@pytest.mark.parametrize("tool_name,agent_type", [("Task", "test-agent"), ("Agent", "code-agent")])
def test_format_tool_call_task_and_agent(tool_name, agent_type):
    formatted, context = _format_tool_call(
        tool_name,
        input_data={"subagent_type": agent_type, "description": "do something"},
        sub_agent_context=None,
    )
    assert "[TASK]" in formatted
    assert agent_type in formatted
    assert context == agent_type


def test_parse_agent_input_with_dict():
    assert _parse_agent_input({"subagent_type": "browser", "description": "open page"}) == ("browser", "open page")


def test_parse_agent_input_missing_fields():
    assert _parse_agent_input({"other": "data"}) == ("unknown", "")


def test_parse_agent_input_non_dict():
    assert _parse_agent_input("some string") == ("unknown", "")


def test_tool_summary_agent():
    assert _tool_summary("Agent", {"subagent_type": "research", "description": "find docs"}) == "Task [research]: find docs"


def test_tool_summary_task():
    assert _tool_summary("Task", {"subagent_type": "code", "description": "write code"}) == "Task [code]: write code"


def test_eventbus_emit_subagent_start():
    bus = EventBus()
    q = bus.subscribe()
    event = SubagentStartEvent(type="subagent_start", agent_id="abc", agent_type="browser")
    bus.emit(event)
    received = q.get_nowait()
    assert received["type"] == "subagent_start"
    assert received["agent_id"] == "abc"
    assert received["agent_type"] == "browser"
    assert len(bus.history) == 1
    assert bus.history[0]["type"] == "subagent_start"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "verb,event_type,agent_id,agent_type",
    [("started", "subagent_start", "test-123", "research"), ("stopped", "subagent_stop", "test-456", "browser")],
)
async def test_subagent_hook_emits_event(verb, event_type, agent_id, agent_type):
    state = vm.State()
    hook = _subagent_hook(state, verb=verb, event_type=event_type)
    q = state.event_bus.subscribe()
    await hook(tp.cast(SubagentStartHookInput, {"agent_id": agent_id, "agent_type": agent_type}), None, tp.cast(HookContext, MagicMock()))
    received = tp.cast(SubagentStartEvent | SubagentStopEvent, q.get_nowait())
    assert received["type"] == event_type
    assert received["agent_id"] == agent_id
    assert received["agent_type"] == agent_type


# --- Deployment validation ---


def test_deployment_structure():
    source_root = Path(__file__).parent.parent
    assert source_root.is_dir()

    skills_dir = source_root / "skills"
    assert skills_dir.is_dir(), "skills/ directory missing"

    expected_skills = [
        "reminders",
        "tasks",
        "upstream",
        "dream",
        "what-day",
        "browser",
        "skills-registry",
        "google",
        "microsoft",
        "whatsapp",
        "whisper",
        "zoom",
        "keeper",
        "onedrive",
    ]
    for skill_name in expected_skills:
        assert (skills_dir / skill_name).is_dir(), f"Skill '{skill_name}' missing from skills/"

    for skill_name in ("reminders", "tasks"):
        assert (skills_dir / skill_name / "cli" / "pyproject.toml").exists(), f"pyproject.toml missing for {skill_name}"

    assert (skills_dir / "whatsapp" / "cli" / "go.mod").exists(), "go.mod missing for whatsapp"


def test_skill_frontmatter():
    import re

    skills_dir = Path(__file__).parent.parent / "skills"
    for skill_md in skills_dir.glob("*/SKILL.md"):
        text = skill_md.read_text()
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        assert match, f"{skill_md}: missing frontmatter"
        fm = dict(re.findall(r"^(\w[\w-]*)\s*:\s*(.+)$", match.group(1), re.MULTILINE))
        assert fm.get("name"), f"{skill_md}: missing 'name' in frontmatter"
        assert fm.get("description"), f"{skill_md}: missing 'description' in frontmatter"


def test_skills_index_valid():
    import json
    import re

    source_root = Path(__file__).parent.parent
    index = json.loads((source_root / "skills" / "index.json").read_text())
    assert isinstance(index, list) and index, "skills/index.json must be a non-empty list"
    skill_names = {s["name"] for s in index}
    for skill_md in (source_root / "skills").glob("*/SKILL.md"):
        text = skill_md.read_text()
        match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
        fm = dict(re.findall(r"^(\w[\w-]*)\s*:\s*(.+)$", match.group(1), re.MULTILINE)) if match else {}
        assert fm.get("name", skill_md.parent.name) in skill_names, f"{skill_md.parent.name} missing from skills/index.json"


def test_skills_registry_scripts_executable():
    scripts_dir = Path(__file__).parent.parent / "skills" / "skills-registry" / "scripts"
    for script in scripts_dir.iterdir():
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"


# --- Message processor tests ---


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

    config = _make_config(tmp_path)
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
async def test_message_processor_resets_on_error(tmp_path):
    call_count = 0

    async def side_effect(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated SDK buffer overflow")
        return (["OK"], state)

    state, session_count, messages = await _run_processor_test(
        tmp_path, message_side_effect=side_effect, initial_queue=[("first message - will fail", True)]
    )
    assert session_count >= 2
    assert any("Previous request failed" in msg for msg in messages)


@pytest.mark.anyio
async def test_message_processor_restart_preserves_session(tmp_path):
    call_count = 0

    async def side_effect(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            state.session_id = "test-session-123"
            state.pending_context = "[System: Vesta restarted.]"
        return (["OK"], state)

    state, session_count, messages = await _run_processor_test(
        tmp_path, message_side_effect=side_effect, initial_queue=[("edit some config", True)]
    )
    assert state.session_id == "test-session-123"
    assert session_count >= 2
    assert any("restarted" in msg.lower() for msg in messages)


@pytest.mark.anyio
async def test_response_timeout_triggers_session_reset(tmp_path):
    call_count = 0

    async def side_effect(msg, *, state, config, is_user):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            state.pending_context = "[System: Response timed out. Session was reset to recover.]"
        return (["OK"], state)

    pre_state = vm.State()
    pre_state.session_id = "timeout-session"
    state, session_count, messages = await _run_processor_test(
        tmp_path, message_side_effect=side_effect, pre_state=pre_state, initial_queue=[("slow request", True)]
    )
    assert session_count >= 2
    assert state.session_id == "timeout-session"
    assert any("timed out" in msg.lower() for msg in messages)


@pytest.mark.anyio
async def test_client_cleared_on_cancellation(tmp_path):
    from vesta.core.loops import message_processor

    config = _make_config(tmp_path)
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


# --- Dreamer tests ---


@pytest.mark.anyio
async def test_dreamer_queues_prompt_and_archives(tmp_path):
    from vesta.core.loops import process_nightly_memory

    state = vm.State()
    state.last_dreamer_run = None
    queue: asyncio.Queue = asyncio.Queue()

    dreamer_hour = 4
    config = vm.VestaConfig(root=tmp_path, nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    with (
        patch("vesta.core.loops._now", return_value=fake_now),
        patch("vesta.core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        await process_nightly_memory(queue, state=state, config=config)

    assert not queue.empty()
    msg, is_user = await queue.get()
    assert msg == "dreamer prompt"
    assert is_user is False
    assert state.last_dreamer_run == fake_now
    assert state.dreamer_active is True


@pytest.mark.anyio
async def test_dreamer_skips_when_already_run_today(tmp_path):
    from vesta.core.loops import process_nightly_memory

    dreamer_hour = 4
    config = vm.VestaConfig(root=tmp_path, nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    state = vm.State()
    state.last_dreamer_run = fake_now
    queue: asyncio.Queue = asyncio.Queue()

    with (
        patch("vesta.core.loops._now", return_value=fake_now),
        patch("vesta.core.loops.load_prompt", return_value="dreamer prompt"),
    ):
        await process_nightly_memory(queue, state=state, config=config)

    assert queue.empty()
    assert state.dreamer_active is False


@pytest.mark.anyio
async def test_dreamer_triggers_automatic_restart(tmp_path):
    async def side_effect(msg, *, state, config, is_user):
        return (["OK"], state)

    pre_state = vm.State()
    pre_state.session_id = "pre-dreamer-session"
    pre_state.dreamer_active = True

    fake_now = dt.datetime(2025, 6, 15, 4, 5, 0)
    state, session_count, messages = await _run_processor_test(
        tmp_path,
        message_side_effect=side_effect,
        pre_state=pre_state,
        initial_queue=[("dreamer prompt content", False)],
        extra_patches={"vesta.core.loops._now": lambda: fake_now},
    )
    assert state.session_id is None
    assert state.dreamer_active is False
    assert session_count >= 2
    assert any("new day" in msg for msg in messages)


# --- Interrupt tests ---


@pytest.mark.anyio
async def test_message_processor_interrupts_on_new_message(tmp_path):
    """New messages arriving during processing set the interrupt event and are processed after."""
    processing_started = asyncio.Event()
    interrupt_seen = asyncio.Event()

    async def slow_side_effect(msg, *, state, config, is_user):
        if "slow" in msg:
            processing_started.set()
            for _ in range(100):
                if state.interrupt_event and state.interrupt_event.is_set():
                    interrupt_seen.set()
                    break
                await asyncio.sleep(0.05)
        return (["OK"], state)

    config = _make_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    await queue.put(("slow processing message", True))

    processed: list[str] = []
    original = slow_side_effect

    async def tracking(msg, *, state, config, is_user):
        processed.append(msg)
        return await original(msg, state=state, config=config, is_user=is_user)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def inject_message_and_shutdown():
        await processing_started.wait()
        await queue.put(("urgent message", True))
        await interrupt_seen.wait()
        await asyncio.sleep(0.1)
        assert state.shutdown_event is not None
        state.shutdown_event.set()

    from vesta.core.loops import message_processor

    with (
        patch("vesta.core.loops.ClaudeSDKClient", return_value=mock_client),
        patch("vesta.core.loops.process_message", tracking),
        patch("vesta.core.loops.build_client_options", return_value=MagicMock()),
    ):
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            inject_message_and_shutdown(),
        )

    assert interrupt_seen.is_set(), "interrupt_event should have been set when new message arrived"
    assert "slow processing message" in processed
    assert "urgent message" in processed


@pytest.mark.anyio
async def test_process_interruptible_cancels_process_task(tmp_path):
    """Cancelling _process_interruptible must cancel its in-flight process_task (no orphaned tasks)."""
    from vesta.core.loops import _process_interruptible

    config = _make_config(tmp_path)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    task_started = asyncio.Event()
    task_cancelled = False

    async def hanging_process(msg, *, state, config, is_user):
        nonlocal task_cancelled
        task_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            task_cancelled = True
            raise
        return (["OK"], state)

    with patch("vesta.core.loops._process_message_safely", hanging_process):
        interruptible_task = asyncio.create_task(_process_interruptible("test msg", is_user=True, queue=queue, state=state, config=config))
        await task_started.wait()
        interruptible_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await interruptible_task

    assert task_cancelled, "process_task should have been cancelled, not left orphaned"


@pytest.mark.anyio
async def test_run_vesta_force_exits_on_hung_cleanup(tmp_path):
    """run_vesta must force-exit if task cleanup hangs (e.g. SDK __aexit__ blocking)."""
    from vesta.main import run_vesta

    config = _make_config(tmp_path)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()

    force_exit_called_with: list[int] = []
    exit_event = asyncio.Event()

    def fake_exit(code):
        force_exit_called_with.append(code)
        exit_event.set()

    async def hanging_on_cancel(*args, **kwargs):
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            # Simulate SDK __aexit__ hanging during cleanup — resist repeated cancellation
            while not exit_event.is_set():
                try:
                    await asyncio.sleep(0.01)
                except asyncio.CancelledError:
                    continue

    with (
        patch("vesta.main.start_ws_server", new_callable=AsyncMock) as mock_ws,
        patch("vesta.main.input_handler", hanging_on_cancel),
        patch("vesta.main.message_processor", hanging_on_cancel),
        patch("vesta.main.monitor_loop", hanging_on_cancel),
        patch("vesta.main.queue_greeting", new_callable=AsyncMock),
        patch("os._exit", fake_exit),
    ):
        mock_ws.return_value = MagicMock()
        mock_ws.return_value.cleanup = AsyncMock()

        async def trigger_shutdown():
            await asyncio.sleep(0.05)
            assert state.graceful_shutdown is not None
            state.graceful_shutdown.set()
            await exit_event.wait()

        await asyncio.gather(run_vesta(config, state=state), trigger_shutdown())

    assert force_exit_called_with == [1], f"os._exit(1) should have been called, got {force_exit_called_with}"


@pytest.mark.anyio
async def test_converse_breaks_on_interrupt_event():
    """converse exits promptly when interrupt_event is set, not waiting for slow response iterator."""
    from vesta.core.client import converse

    yielded_count = 0

    async def slow_response():
        nonlocal yielded_count
        msg = MagicMock()
        msg.content = []
        yielded_count += 1
        yield msg
        await asyncio.sleep(10)
        yielded_count += 1
        yield msg

    config = vm.VestaConfig(interrupt_timeout=0.5)
    state = vm.State()
    state.interrupt_event = asyncio.Event()

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=slow_response())
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    async def trigger_interrupt():
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()

    asyncio.create_task(trigger_interrupt())

    import time

    start = time.monotonic()
    await converse("test prompt", state=state, config=config, show_output=False)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"converse should have exited promptly but took {elapsed:.1f}s"
    assert mock_client.interrupt.called, "interrupt should have been called"
    assert yielded_count == 1, "should have only yielded once before interrupt"


@pytest.mark.anyio
async def test_converse_works_normally_without_interrupt():
    """converse processes all messages when no interrupt is set."""
    from vesta.core.client import converse

    messages_yielded = 0

    async def normal_response():
        nonlocal messages_yielded
        for _ in range(3):
            msg = MagicMock()
            msg.content = []
            messages_yielded += 1
            yield msg

    config = vm.VestaConfig()
    state = vm.State()

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.receive_response = MagicMock(return_value=normal_response())
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    await converse("test prompt", state=state, config=config, show_output=False)

    assert messages_yielded == 3, "all messages should have been processed"
    assert not mock_client.interrupt.called, "interrupt should not have been called"


# --- Converse / streaming e2e helpers ---


def _assistant_msg(content):
    from claude_agent_sdk import AssistantMessage

    msg = MagicMock(spec=AssistantMessage)
    msg.content = content
    return msg


def _result_msg():
    from claude_agent_sdk import ResultMessage

    msg = MagicMock(spec=ResultMessage)
    msg.content = []
    return msg


def _make_converse_harness(*, use_shared_queue: bool = False):
    """Build a converse() test harness with tracking and a mock SDK client.

    Returns (state, config, mock_client, emitted, message_queue).
    message_queue is only set if use_shared_queue=True (for multi-converse tests).
    """
    import time

    emitted: list[tuple[str, float]] = []
    config = vm.VestaConfig(interrupt_timeout=0.5)
    state = vm.State()
    state.event_bus = EventBus()

    original_emit = state.event_bus.emit

    def tracking_emit(event):
        if isinstance(event, dict) and event.get("type") == "assistant":
            emitted.append((event["text"], time.monotonic()))
        original_emit(event)

    state.event_bus.emit = tracking_emit  # type: ignore[assignment]

    mock_client = MagicMock()
    mock_client.query = AsyncMock()
    mock_client.interrupt = AsyncMock()
    state.client = mock_client

    message_queue: asyncio.Queue[tp.Any] | None = None
    if use_shared_queue:
        message_queue = asyncio.Queue()

        async def _receive_response():
            from claude_agent_sdk import ResultMessage

            while True:
                msg = await message_queue.get()
                yield msg
                if isinstance(msg, ResultMessage):
                    return

        mock_client.receive_response = MagicMock(side_effect=lambda: _receive_response())

    return state, config, mock_client, emitted, message_queue


# --- Converse / streaming regression tests ---


def test_filter_tool_lines():
    """filter_tool_lines must keep normal text and only strip [TOOL]/[TASK] prefixed lines."""
    from vesta.core.client import filter_tool_lines

    assert filter_tool_lines("hello world") == "hello world"
    assert filter_tool_lines("[TOOL] Bash: ls\nthe result") == "the result"
    assert filter_tool_lines("[TASK] [browser]: search\nfound it") == "found it"
    assert filter_tool_lines("[TOOL] done\n[TASK] done") == ""
    assert filter_tool_lines("line one\n  \nline two") == "line one\nline two"
    assert filter_tool_lines("") == ""


def test_process_message_always_streams():
    """process_message must always pass show_output=True — regression guard."""
    import ast
    import inspect

    from vesta.core.client import process_message

    source = inspect.getsource(process_message)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "show_output":
            val = node.value
            assert isinstance(val, ast.Constant) and val.value is True, (
                f"process_message must pass show_output=True to converse(), found show_output={ast.dump(val)}"
            )


@pytest.mark.anyio
async def test_converse_emits_text_immediately_with_tool_use():
    """Text in messages that also have tool_use must be emitted immediately, not buffered."""
    from claude_agent_sdk import TextBlock, ToolUseBlock
    from vesta.core.client import converse

    state, config, mock_client, emitted, _ = _make_converse_harness()

    async def response_with_tool_use():
        yield _assistant_msg([TextBlock("restarting daemon"), ToolUseBlock("1", "Bash", {})])
        yield _assistant_msg([TextBlock("checking status"), ToolUseBlock("2", "Bash", {})])
        yield _assistant_msg([TextBlock("all done")])

    mock_client.receive_response = MagicMock(return_value=response_with_tool_use())

    await converse("test", state=state, config=config, show_output=True)

    texts = [t for t, _ in emitted]
    assert texts == ["restarting daemon", "checking status", "all done"], f"All text must be emitted immediately, got: {texts}"


@pytest.mark.anyio
async def test_interrupt_drains_stream_and_emits_leftovers():
    """After an interrupt, leftover messages must be emitted (not lost)
    and must NOT leak into the next converse() call."""
    import time

    from claude_agent_sdk import TextBlock, ToolUseBlock
    from vesta.core.client import converse

    state, config, mock_client, emitted, message_queue = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    # --- Conv 1: interrupted, has a leftover ---
    state.interrupt_event = asyncio.Event()

    async def sim_conv1():
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()
        await asyncio.sleep(0.1)
        await message_queue.put(_assistant_msg([TextBlock("here are the files")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv1())
    await converse("list /tmp", state=state, config=config, show_output=True)

    assert any(t == "here are the files" for t, _ in emitted), f"Leftover must be emitted during drain: {[t for t, _ in emitted]}"

    # --- Conv 2: must NOT see conv 1's leftovers ---
    state.interrupt_event = None
    n_before = len(emitted)

    async def sim_conv2():
        await asyncio.sleep(0.3)
        await message_queue.put(_assistant_msg([TextBlock("fresh response")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv2())
    t0 = time.monotonic()
    await converse("well?", state=state, config=config, show_output=True)

    conv2 = emitted[n_before:]
    assert len(conv2) == 1 and conv2[0][0] == "fresh response", f"Conv 2 got wrong messages: {[t for t, _ in conv2]}"
    delay_ms = (conv2[0][1] - t0) * 1000
    assert delay_ms > 100, f"Response at +{delay_ms:.0f}ms — too fast, likely leaked from conv 1"


@pytest.mark.anyio
async def test_interrupt_then_response_arrives_without_user_input():
    """Reproduces the exact bug from docker logs: user conversation is interrupted
    by a notification, notification does tool calls then responds — that response
    must arrive on its own without the user sending another message.

    Real timeline:
      12:28:02 USER: "i did it instantly..."
      12:28:21 INTERRUPT (notification)
      12:28:27 TOOL: Bash (restart daemon)
      12:28:30 TOOL: done
      -- 62 seconds stuck --
      12:29:32 USER: "well?" → ASSISTANT appears instantly"""
    import time

    from claude_agent_sdk import TextBlock, ToolUseBlock
    from vesta.core.client import converse

    state, config, mock_client, emitted, message_queue = _make_converse_harness(use_shared_queue=True)
    assert message_queue is not None

    # --- Conv 1: user message interrupted by notification ---
    state.interrupt_event = asyncio.Event()

    async def sim_conv1():
        await asyncio.sleep(0.05)
        await message_queue.put(_assistant_msg([ToolUseBlock("1", "Bash", {})]))
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()
        await asyncio.sleep(0.1)
        await message_queue.put(_assistant_msg([TextBlock("checking logs")]))
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv1())
    await converse("i did it instantly", state=state, config=config, show_output=True)

    assert any(t == "checking logs" for t, _ in emitted), f"Conv 1 leftover not emitted: {[t for t, _ in emitted]}"

    # --- Conv 2: notification processing (was STUCK in the real bug) ---
    state.interrupt_event = None
    n_before = len(emitted)
    t0 = time.monotonic()

    async def sim_conv2():
        await asyncio.sleep(0.05)
        await message_queue.put(_assistant_msg([ToolUseBlock("2", "Bash", {})]))
        await asyncio.sleep(0.2)
        await message_queue.put(_assistant_msg([TextBlock("daemon's back up")]))
        await asyncio.sleep(0.05)
        await message_queue.put(_result_msg())

    asyncio.create_task(sim_conv2())
    await converse("daemon_died notification", state=state, config=config, show_output=True)

    conv2_texts = [t for t, _ in emitted[n_before:]]
    assert "daemon's back up" in conv2_texts, f"Conv 2 response must arrive without user interaction: {conv2_texts}"
    for text, t in emitted[n_before:]:
        if text == "daemon's back up":
            delay_ms = (t - t0) * 1000
            assert delay_ms < 2000, f"'{text}' took {delay_ms:.0f}ms — agent was stuck"


@pytest.mark.anyio
async def test_drain_timeout_does_not_block_forever():
    """If the SDK is slow to send ResultMessage after interrupt, the drain must
    time out and not block the next conversation forever."""
    from claude_agent_sdk import ToolUseBlock
    from vesta.core.client import converse

    state, config, mock_client, _, _ = _make_converse_harness()

    call_count = 0

    async def slow_drain_response():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: normal conversation that gets interrupted
            yield _assistant_msg([ToolUseBlock("1", "Bash", {})])
            await asyncio.sleep(60)  # Hangs — simulates SDK not sending ResultMessage
        else:
            # Drain call: also hangs (SDK is stuck)
            await asyncio.sleep(60)

    mock_client.receive_response = MagicMock(side_effect=lambda: slow_drain_response())
    state.client = mock_client
    state.interrupt_event = asyncio.Event()

    async def trigger():
        await asyncio.sleep(0.1)
        assert state.interrupt_event is not None
        state.interrupt_event.set()

    import time

    asyncio.create_task(trigger())
    t0 = time.monotonic()
    await converse("test", state=state, config=config, show_output=True)
    elapsed = time.monotonic() - t0

    # Must exit within drain timeout (5s) + some margin, not hang for 60s
    assert elapsed < 8.0, f"converse took {elapsed:.1f}s — drain blocked too long"


# --- Nightly restart ---


def test_nightly_restart(tmp_path):
    from vesta.core.loops import _trigger_nightly_restart

    config = vm.VestaConfig(root=tmp_path)
    fake_now = dt.datetime(2025, 6, 15, 4, 5, 0)

    # With summary
    state = vm.State(session_id="old-session")
    config.dreamer_dir.mkdir(parents=True, exist_ok=True)
    (config.dreamer_dir / "2025-06-15.md").write_text("Updated MEMORY.md, pruned stale entries.")

    with patch("vesta.core.loops._now", return_value=fake_now):
        _trigger_nightly_restart(state=state, config=config)

    assert state.session_id is None
    assert state.pending_context is not None
    assert "new day" in state.pending_context
    assert "Updated MEMORY.md" in state.pending_context

    # Without summary
    state2 = vm.State(session_id="other-session")
    (config.dreamer_dir / "2025-06-15.md").unlink()

    with patch("vesta.core.loops._now", return_value=fake_now):
        _trigger_nightly_restart(state=state2, config=config)

    assert state2.session_id is None
    assert state2.pending_context is not None
    assert "new day" in state2.pending_context
    assert "Dreamer Summary" not in state2.pending_context


# --- History store ---


def test_history_store_save_and_search(tmp_path):
    store = open_history(tmp_path / "test.db")
    history_save(store, "user", "what is the weather in paris")
    history_save(store, "assistant", "it is sunny in paris today")
    history_save(store, "user", "how about london")
    history_save(store, "assistant", "london is rainy as usual")

    results = history_search(store, "paris")
    assert len(results) == 2
    assert any("paris" in r["content"] for r in results)

    results = history_search(store, "london")
    assert len(results) == 2

    results = history_search(store, "sunny")
    assert len(results) == 1
    assert results[0]["role"] == "assistant"


def test_history_store_search_no_results(tmp_path):
    store = open_history(tmp_path / "test.db")
    history_save(store, "user", "hello world")
    results = history_search(store, "nonexistent")
    assert results == []


def test_history_store_search_limit(tmp_path):
    store = open_history(tmp_path / "test.db")
    for i in range(10):
        history_save(store, "user", f"message number {i} about python")

    results = history_search(store, "python", limit=3)
    assert len(results) == 3


def test_history_store_get_range(tmp_path):
    store = open_history(tmp_path / "test.db")
    t1 = dt.datetime(2025, 1, 1, 10, 0, 0)
    t2 = dt.datetime(2025, 1, 2, 10, 0, 0)
    t3 = dt.datetime(2025, 1, 3, 10, 0, 0)
    history_save(store, "user", "day one", timestamp=t1)
    history_save(store, "user", "day two", timestamp=t2)
    history_save(store, "user", "day three", timestamp=t3)

    results = history_get_range(store, since=t2)
    assert len(results) == 2
    assert results[0]["content"] == "day two"

    results = history_get_range(store, until=t2)
    assert len(results) == 2
    assert results[1]["content"] == "day two"


def test_history_format_results():
    assert format_results([]) == "No results found."

    results = [{"timestamp": "2025-01-01T10:00:00", "role": "user", "content": "hello"}]
    formatted = format_results(results)
    assert "hello" in formatted
    assert "user" in formatted


def test_history_store_session_id(tmp_path):
    store = open_history(tmp_path / "test.db")
    history_save(store, "user", "msg one", session_id="session-abc")
    history_save(store, "user", "msg two", session_id="session-def")

    results = history_search(store, "msg")
    assert len(results) == 2
