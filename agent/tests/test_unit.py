"""Unit tests for Vesta core modules."""

import asyncio
import datetime as dt
import typing as tp
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import vesta.models as vm
from claude_agent_sdk import HookContext
from claude_agent_sdk.types import SubagentStartHookInput, SubagentStopHookInput
from vesta.core.client import _format_tool_call, _parse_agent_input, _tool_summary, _subagent_hook
from vesta.events import EventBus, SubagentStartEvent
from vesta.core.init import get_memory_path
from vesta.core.loops import format_notification_batch


def _make_config(tmp_path: Path) -> vm.VestaConfig:
    return vm.VestaConfig(state_dir=tmp_path)


# --- Config & init ---


def test_config_paths_under_state_dir(tmp_path):
    config = _make_config(tmp_path)
    assert config.notifications_dir.is_relative_to(tmp_path)
    assert config.data_dir.is_relative_to(tmp_path)
    assert config.logs_dir.is_relative_to(tmp_path)
    assert config.memory_dir.is_relative_to(config.install_root)
    assert config.skills_dir.is_relative_to(config.install_root)


def test_config_default_values():
    config = vm.VestaConfig()
    assert config.notification_check_interval > 0
    assert config.response_timeout > 0


def test_memory_paths(tmp_path):
    config = _make_config(tmp_path)
    assert config.memory_dir == config.install_root / "memory"
    assert get_memory_path(config) == config.install_root / "memory" / "MEMORY.md"
    assert config.skills_dir == config.install_root / "memory" / "skills"


# --- Formatting ---


def test_format_tool_call_task():
    formatted, context = _format_tool_call(
        "Task",
        input_data={"subagent_type": "test-agent", "description": "do something"},
        sub_agent_context=None,
    )
    assert "[TASK]" in formatted
    assert "test-agent" in formatted
    assert context == "test-agent"


def test_format_tool_call_agent():
    formatted, context = _format_tool_call(
        "Agent",
        input_data={"subagent_type": "code-agent", "description": "write tests"},
        sub_agent_context=None,
    )
    assert "[TASK]" in formatted
    assert "code-agent" in formatted
    assert context == "code-agent"


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
async def test_subagent_hook_emits_start_event():
    state = vm.State()
    hook = _subagent_hook(state, verb="started", event_type="subagent_start")
    q = state.event_bus.subscribe()
    await hook(tp.cast(SubagentStartHookInput, {"agent_id": "test-123", "agent_type": "research"}), None, tp.cast(HookContext, MagicMock()))
    received = q.get_nowait()
    assert received["type"] == "subagent_start"
    assert received["agent_id"] == "test-123"
    assert received["agent_type"] == "research"


@pytest.mark.anyio
async def test_subagent_hook_emits_stop_event():
    state = vm.State()
    hook = _subagent_hook(state, verb="stopped", event_type="subagent_stop")
    q = state.event_bus.subscribe()
    await hook(tp.cast(SubagentStopHookInput, {"agent_id": "test-456", "agent_type": "browser"}), None, tp.cast(HookContext, MagicMock()))
    received = q.get_nowait()
    assert received["type"] == "subagent_stop"
    assert received["agent_id"] == "test-456"
    assert received["agent_type"] == "browser"


def test_format_notification_batch_single():
    notif = vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message")
    formatted = format_notification_batch([notif])
    assert "[NOTIFICATIONS]" not in formatted


def test_format_notification_batch_multiple():
    notifs = [
        vm.Notification(timestamp=dt.datetime(2025, 1, 1), source="test", type="message"),
        vm.Notification(timestamp=dt.datetime(2025, 1, 1, 0, 0, 1), source="test", type="message"),
    ]
    formatted = format_notification_batch(notifs)
    assert "[NOTIFICATIONS]" in formatted


# --- Deployment validation ---


def test_deployment_structure():
    config = vm.VestaConfig()
    assert config.install_root.is_dir()

    tools_dir = config.install_root / "tools"
    assert tools_dir.is_dir()

    whatsapp_dir = tools_dir / "whatsapp"
    assert (whatsapp_dir / "go.mod").exists()
    assert (whatsapp_dir / "main.go").exists()

    for tool_name in ["microsoft", "reminder", "tasks"]:
        assert (tools_dir / tool_name / "pyproject.toml").exists(), f"pyproject.toml missing for {tool_name}"


def test_skills_discovered():
    from vesta.core.init import _discover_skills

    config = vm.VestaConfig()
    skills = _discover_skills(config)
    expected = {
        "browser",
        "google",
        "keeper",
        "microsoft",
        "onedrive",
        "reminders",
        "tasks",
        "upstream",
        "what-day",
        "whatsapp",
        "whisper",
        "zoom",
    }
    assert set(skills.keys()) == expected

    for name, path in skills.items():
        assert (path / "SKILL.md").exists(), f"SKILL.md missing for {name}"


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
    # Use ExitStack to apply all patches
    import contextlib

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
    config = vm.VestaConfig(state_dir=tmp_path, nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    with (
        patch("vesta.core.loops._now", return_value=fake_now),
        patch("vesta.core.loops.build_dreamer_prompt", return_value="dreamer prompt"),
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
    config = vm.VestaConfig(state_dir=tmp_path, nightly_memory_hour=dreamer_hour)
    fake_now = dt.datetime(2025, 6, 15, dreamer_hour, 0, 0)

    state = vm.State()
    state.last_dreamer_run = fake_now
    queue: asyncio.Queue = asyncio.Queue()

    with (
        patch("vesta.core.loops._now", return_value=fake_now),
        patch("vesta.core.loops.build_dreamer_prompt", return_value="dreamer prompt"),
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


# --- Nightly restart ---


def test_nightly_restart(tmp_path):
    from vesta.core.loops import _trigger_nightly_restart

    config = vm.VestaConfig(state_dir=tmp_path)
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
    from vesta.core.history import open_history, history_save, history_search

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
    from vesta.core.history import open_history, history_save, history_search

    store = open_history(tmp_path / "test.db")
    history_save(store, "user", "hello world")
    results = history_search(store, "nonexistent")
    assert results == []


def test_history_store_search_limit(tmp_path):
    from vesta.core.history import open_history, history_save, history_search

    store = open_history(tmp_path / "test.db")
    for i in range(10):
        history_save(store, "user", f"message number {i} about python")

    results = history_search(store, "python", limit=3)
    assert len(results) == 3


def test_history_store_get_range(tmp_path):
    from vesta.core.history import open_history, history_save, history_get_range

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
    from vesta.core.history import format_results

    assert format_results([]) == "No results found."

    results = [{"timestamp": "2025-01-01T10:00:00", "role": "user", "content": "hello"}]
    formatted = format_results(results)
    assert "hello" in formatted
    assert "user" in formatted


def test_history_store_session_id(tmp_path):
    from vesta.core.history import open_history, history_save, history_search

    store = open_history(tmp_path / "test.db")
    history_save(store, "user", "msg one", session_id="session-abc")
    history_save(store, "user", "msg two", session_id="session-def")

    results = history_search(store, "msg")
    assert len(results) == 2
