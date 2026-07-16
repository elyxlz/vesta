"""Tests for message processor: error recovery, timeout, restart, cancellation."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import core.models as vm
import core.config as cfg
from conftest import idle_message_stream
from core.client import process_message
from wait_util import wait_for_condition


async def _run_processor_test(
    tmp_path,
    *,
    message_side_effect,
    pre_state: vm.State | None = None,
    initial_queue: list[vm.QueuedTurn] | None = None,
    extra_patches: dict | None = None,
):
    """Shared helper for message_processor tests."""
    from core.loops import message_processor

    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = pre_state or vm.State()
    # These tests exercise the active processing path; an authenticated provider lets message_processor
    # build the (mocked) client rather than idling. Tests of the unauthenticated path set their own.
    if state.provider_status is None:
        state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
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
    mock_client.receive_messages = idle_message_stream

    async def mock_enter(self):
        nonlocal session_count
        session_count += 1
        return mock_client

    mock_client.__aenter__ = mock_enter
    mock_client.__aexit__ = AsyncMock(return_value=None)

    expected_message_count = len(initial_queue or [])

    async def shutdown_when_done():
        # Done = the processor restarted itself (error paths) or finished every queued message.
        await wait_for_condition(
            lambda: state.graceful_shutdown.is_set() or (len(processed_messages) >= expected_message_count and not state.processor_busy)
        )
        assert state.shutdown_event is not None
        state.shutdown_event.set()

    patches = {
        "core.client.ClaudeSDKClient": mock_client,
        "core.loops.process_message": tracking_process_message,
        "core.client.build_client_options": MagicMock(),
    }
    if extra_patches:
        patches.update(extra_patches)

    ctx_managers = [patch(k, v if not callable(v) or isinstance(v, MagicMock) else v) for k, v in patches.items()]
    with contextlib.ExitStack() as stack:
        for cm in ctx_managers:
            stack.enter_context(cm)
        await asyncio.gather(
            message_processor(queue, state=state, config=config),
            shutdown_when_done(),
        )

    return state, session_count, processed_messages


@pytest.mark.anyio
async def test_restarts_on_error(tmp_path):
    async def side_effect(msg, *, state, config, is_user):
        raise RuntimeError("Simulated SDK buffer overflow")

    state, session_count, messages = await _run_processor_test(
        tmp_path, message_side_effect=side_effect, initial_queue=[vm.QueuedTurn("first message - will fail", True, [])]
    )
    assert state.graceful_shutdown.is_set()
    assert state.persisted.last_restart_reason == "error: Simulated SDK buffer overflow"


@pytest.mark.anyio
async def test_error_path_emits_error_event_and_resets_state_idle(tmp_path):
    """The crash path must reach the observability surface: an {"type":"error"} event on the bus, state back to idle.

    Pins the emit at loops.py error handler so a refactor that drops it (leaving clients blind to a crash)
    fails CI, alongside the existing last_restart_reason assertion."""
    state = vm.State()
    subscriber = state.event_bus.subscribe()

    async def side_effect(msg, *, state, config, is_user):
        raise RuntimeError("kaboom in the SDK")

    state, _, _ = await _run_processor_test(
        tmp_path,
        message_side_effect=side_effect,
        pre_state=state,
        initial_queue=[vm.QueuedTurn("will crash", True, [])],
    )

    assert state.persisted.last_restart_reason == "error: kaboom in the SDK"
    assert state.event_bus.state == "idle", "bus state must reset to idle after the crash path"

    drained = []
    while not subscriber.empty():
        drained.append(subscriber.get_nowait())
    error_events = [e for e in drained if e["type"] == "error"]
    assert len(error_events) == 1, f"exactly one error event expected, got {[e['type'] for e in drained]}"
    assert error_events[0]["text"] == "kaboom in the SDK"


@pytest.mark.anyio
async def test_restarts_on_timeout(tmp_path):
    """An SDK hang surfaces as a response TimeoutError. The processor records it as an `error:`
    reason, and that reason must classify as a CRASH so main() exits non-zero and Docker's
    on-failure policy restarts the container — under on-failure a clean exit 0 would leave the agent
    hung-then-permanently-down."""

    async def side_effect(msg, *, state, config, is_user):
        raise TimeoutError()

    state, session_count, messages = await _run_processor_test(
        tmp_path, message_side_effect=side_effect, initial_queue=[vm.QueuedTurn("slow request", True, [])]
    )
    assert state.graceful_shutdown.is_set()
    assert state.persisted.last_restart_reason == "error: Response timed out"
    assert vm.is_crash_reason(state.persisted.last_restart_reason), "an SDK-hang timeout must classify as a crash so on-failure restarts it"


def test_restart_reason_round_trip(tmp_path):
    """Persisted restart_reason survives across load_state and is consumed by _consume_restart_reason."""
    from core import state_store
    from core.main import _consume_restart_reason

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    state = vm.State()
    state.persisted.last_restart_reason = "nightly: conversation history reset, dreamer ran"
    state_store.save_state(state.persisted, config)

    reloaded = vm.State(persisted=state_store.load_state(config))
    assert _consume_restart_reason(reloaded, config, first_start=False) == "nightly: conversation history reset, dreamer ran"

    # Consumed: a fresh load now reports CRASH_RESTART.
    again = vm.State(persisted=state_store.load_state(config))
    assert _consume_restart_reason(again, config, first_start=False) == vm.CRASH_RESTART


def test_reason_constants_follow_category_detail_shape():
    for const in (vm.CLEAN_RESTART, vm.CRASH_RESTART):
        assert ": " in const, f"{const!r} must be 'category: detail'"
        category = const.split(": ", 1)[0]
        assert category in {"clean", "crash", "error"}, category
        assert "—" not in const and "–" not in const
    assert vm.CLEAN_RESTART == "clean: routine restart, no specific reason"


def test_build_restart_context_renders_system_restart_header(tmp_path):
    from core import helpers

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    # core_prompts_dir == agent_dir/core/prompts; write a stand-in restart.md so load_prompt resolves.
    config.core_prompts_dir.mkdir(parents=True, exist_ok=True)
    (config.core_prompts_dir / "restart.md").write_text("Read the `restart` skill and follow it.\n")

    reason = "clean: routine restart, no specific reason"
    out = helpers.build_restart_context(reason, config)
    assert out.startswith("[System Restart]\nReason: routine restart, no specific reason")
    assert out.endswith("Read the `restart` skill and follow it.")

    # A reason without a category prefix renders whole.
    out2 = helpers.build_restart_context("first start", config)
    assert "Reason: first start" in out2

    # Extras (e.g. a compaction boot message) slot between the header and the restart prompt.
    out3 = helpers.build_restart_context(reason, config, extras=["[Boot Message]\nhello"])
    header, summary, prompt = out3.split("\n\n")
    assert header.startswith("[System Restart]")
    assert summary.startswith("[Boot Message]")
    assert prompt == "Read the `restart` skill and follow it."

    # Crash/error reasons keep their marker: the restart skill branches on a crash boot
    # ("crash -> mention it"), so the category must stay visible for dynamic crash strings.
    out4 = helpers.build_restart_context("crash: JSONDecodeError: Expecting value", config)
    assert "Reason: crash: JSONDecodeError: Expecting value" in out4
    out5 = helpers.build_restart_context("error: Response timed out", config)
    assert "Reason: error: Response timed out" in out5


def test_consume_restart_reason_drains_pending_inbox(tmp_path):
    from core.main import _consume_restart_reason

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    state = vm.State()
    state.persisted.last_restart_reason = vm.CLEAN_RESTART

    # No inbox -> existing behavior (returns the persisted reason).
    assert _consume_restart_reason(state, config, first_start=False) == vm.CLEAN_RESTART

    # Inbox present -> it wins over the persisted clean reason and the file is removed one-shot.
    state.persisted.last_restart_reason = vm.CLEAN_RESTART
    (config.data_dir / "pending_restart_reason").write_text("mounts: you now have read-only access to /media/Plex\n")
    got = _consume_restart_reason(state, config, first_start=False)
    assert got == "mounts: you now have read-only access to /media/Plex"
    assert not (config.data_dir / "pending_restart_reason").exists()

    # Drained: the next boot falls back to CRASH_RESTART like any consumed reason.
    assert _consume_restart_reason(state, config, first_start=False) == vm.CRASH_RESTART


def test_pending_inbox_never_masks_a_crash_reason(tmp_path):
    from core.main import _consume_restart_reason

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    state = vm.State()
    state.persisted.last_restart_reason = "crash: TypeError: boom"
    (config.data_dir / "pending_restart_reason").write_text("backup: you were paused for a scheduled backup\n")

    # The crash the prior run recorded wins over the external reason, and the inbox is still
    # consumed so it can't fire stale on a later boot.
    assert _consume_restart_reason(state, config, first_start=False) == "crash: TypeError: boom"
    assert not (config.data_dir / "pending_restart_reason").exists()


def test_first_start_drains_the_inbox_so_it_cannot_fire_later(tmp_path):
    from core.main import _consume_restart_reason

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)

    state = vm.State()
    (config.data_dir / "pending_restart_reason").write_text("mounts: you now have access to /media/Plex (read-only)\n")

    assert _consume_restart_reason(state, config, first_start=True) == vm.FIRST_START_REASON
    assert not (config.data_dir / "pending_restart_reason").exists(), "a stale inbox must not fire on a later boot"


@pytest.mark.anyio
async def test_client_cleared_on_cancellation(tmp_path):
    from core.loops import message_processor
    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    mock_client = MagicMock()
    mock_client.receive_messages = idle_message_stream
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("core.client.ClaudeSDKClient", return_value=mock_client),
        patch("core.client.build_client_options", return_value=MagicMock()),
    ):
        task = asyncio.create_task(message_processor(queue, state=state, config=config))
        await wait_for_condition(lambda: state.client is mock_client, message="processor never set state.client")

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert state.client is None


# --- Intentional restart mid-notification-turn: drop the file so it isn't re-delivered ---


@pytest.mark.anyio
async def test_notification_dropped_before_intentional_restart(tmp_path):
    """A notification turn that ends with the agent calling restart_vesta must delete the
    notification file before the restart, so it isn't re-delivered on the next boot.

    At-least-once keeps the file until the turn completes (crash recovery), but an intentional
    restart mid-turn means the notification was handled — dropping it here avoids the duplicate the
    SIGTERM-beats-cleanup race would otherwise produce."""
    from core.tools import _vesta_tools

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.notifications_dir.mkdir(parents=True, exist_ok=True)
    notif_file = config.notifications_dir / "whatsapp-123.json"
    notif_file.write_text("{}")

    state = vm.State()
    subscriber = state.event_bus.subscribe()

    async def side_effect(msg, *, state, config, is_user):
        # Mid-turn: the loop has exposed the in-flight notification; the agent handles it and
        # asks to restart. The restart tool must drop the file here, not leave it for the loop's
        # post-turn cleanup that the SIGTERM would beat.
        assert state.in_flight_notification_paths == [str(notif_file)]
        restart = next(t.handler for t in _vesta_tools(state, config) if t.name == "restart_vesta")
        await restart({})

    with patch("core.vestad_client.request_restart", new_callable=AsyncMock, return_value=True):
        state, _, _ = await _run_processor_test(
            tmp_path,
            message_side_effect=side_effect,
            pre_state=state,
            initial_queue=[vm.QueuedTurn("<notification/>", False, [str(notif_file)])],
        )

    assert not notif_file.exists(), "handled notification must be gone before the restart, not re-delivered"
    assert state.in_flight_notification_paths == []

    drained = []
    while not subscriber.empty():
        drained.append(subscriber.get_nowait())
    cleared = [e for e in drained if e["type"] == "notification_cleared"]
    assert [e["notif_id"] for e in cleared] == ["whatsapp-123"], "clients must be told the notification cleared"


# --- Em/en dash correction in process_message ---


@pytest.mark.anyio
async def test_process_message_sends_correction_on_em_dash(tmp_path):
    """process_message should call converse a second time when an em dash is detected."""
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        if len(converse_calls) == 1:
            return vm.TurnSignals(texts=["something \u2014 with an em dash"])
        return vm.TurnSignals(texts=["corrected response"])

    with patch("core.client.converse", side_effect=mock_converse):
        responses, _ = await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 2
    assert "em dash" in converse_calls[1].lower()
    assert responses == ["something \u2014 with an em dash"]


@pytest.mark.parametrize(
    "response",
    [["clean response, no dashes here"], []],
    ids=["no-dashes", "empty-response"],
)
@pytest.mark.anyio
async def test_process_message_no_correction(tmp_path, response):
    """process_message should not send a correction when no dashes are present (incl. an empty response)."""
    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    converse_calls: list[str] = []

    async def mock_converse(prompt, *, state, config, show_output):
        converse_calls.append(prompt)
        return vm.TurnSignals(texts=response)

    with patch("core.client.converse", side_effect=mock_converse):
        await process_message("hello", state=state, config=config, is_user=True)

    assert len(converse_calls) == 1


@pytest.mark.anyio
async def test_unauthenticated_agent_idles_without_building_client(tmp_path):
    """A boot with no authenticated provider must NOT build an SDK client (which requires a provider) —
    it idles until sign-in restarts the process. Regression: build_client_options was called eagerly at
    session start and crashed an unprovisioned agent."""
    from core.loops import message_processor
    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    state.provider_status = ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind="none", model=None)
    queue: asyncio.Queue = asyncio.Queue()

    built = MagicMock()
    with (
        patch("core.client.build_client_options", built),
        patch("core.client.ClaudeSDKClient") as mock_client,
    ):
        task = asyncio.create_task(message_processor(queue, state=state, config=config))
        await asyncio.sleep(0.05)
        assert not task.done()  # idling, not crashed or returned early
        state.shutdown_event.set()
        await asyncio.wait_for(task, timeout=1.0)

    built.assert_not_called()
    mock_client.assert_not_called()
    assert state.client is None


@pytest.mark.anyio
async def test_message_deferred_when_provider_not_authenticated(tmp_path):
    """When already not_authenticated, the processor must not drive claude (a dead token burns the
    full retry budget) AND must not delete the notification file — it has to re-run after re-auth."""
    import asyncio

    from core.loops import _run_messages_with_preempts
    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind="claude", model=None)
    drove_claude = False

    async def mock_process_message(*args, **kwargs):
        nonlocal drove_claude
        drove_claude = True
        return ([], state)

    notif_file = tmp_path / "notif.json"
    notif_file.write_text("{}")
    queue: asyncio.Queue = asyncio.Queue()
    with patch("core.loops.process_message", side_effect=mock_process_message):
        await _run_messages_with_preempts(vm.QueuedTurn("migration notif", False, [str(notif_file)]), queue=queue, state=state, config=config)

    assert drove_claude is False
    assert notif_file.exists(), "deferred notification file must survive for re-run after re-auth"


@pytest.mark.anyio
async def test_notification_file_kept_when_auth_lost_mid_turn(tmp_path):
    """If a turn flips auth to not_authenticated while processing (terminal 401/402 detected in
    converse), that message's notification file must be kept so it re-runs after re-auth."""
    import asyncio

    from core.loops import _run_messages_with_preempts
    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    async def mock_process_message(*args, **kwargs):
        # Simulate converse detecting a dead token mid-turn.
        state.provider_status = ProviderStatus(state=ProviderAuthState.NOT_AUTHENTICATED, kind="claude", model=None)
        return ([], state)

    notif_file = tmp_path / "notif.json"
    notif_file.write_text("{}")
    queue: asyncio.Queue = asyncio.Queue()
    with patch("core.loops.process_message", side_effect=mock_process_message):
        await _run_messages_with_preempts(vm.QueuedTurn("notif", False, [str(notif_file)]), queue=queue, state=state, config=config)

    assert notif_file.exists(), "file for the turn that lost auth must survive for re-run after re-auth"


@pytest.mark.anyio
async def test_notification_file_deleted_on_normal_processing(tmp_path):
    """Sanity: an authenticated, normally-processed notification still has its file deleted."""
    import asyncio

    from core.loops import _run_messages_with_preempts
    from core.provider import ProviderAuthState, ProviderStatus

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    state = vm.State()
    state.provider_status = ProviderStatus(state=ProviderAuthState.AUTHENTICATED, kind="claude", model="opus")

    async def mock_process_message(*args, **kwargs):
        return ([], state)

    notif_file = tmp_path / "notif.json"
    notif_file.write_text("{}")
    sub = state.event_bus.subscribe()
    queue: asyncio.Queue = asyncio.Queue()
    with patch("core.loops.process_message", side_effect=mock_process_message):
        await _run_messages_with_preempts(vm.QueuedTurn("notif", False, [str(notif_file)]), queue=queue, state=state, config=config)

    assert not notif_file.exists(), "normally-processed notification file should be deleted"
    # The clear must also be announced on the stream, so live clients flip the row from pending to
    # cleared without re-polling disk.
    cleared = [e for e in (sub.get_nowait() for _ in range(sub.qsize())) if e["type"] == "notification_cleared"]
    assert len(cleared) == 1
    assert cleared[0]["notif_id"] == "notif"


@pytest.mark.anyio
async def test_cancellation_triggers_restart(tmp_path):
    """If process_message raises CancelledError, restart_reason + graceful_shutdown must be set.

    Regression test for a silent-death bug: CancelledError used to propagate uncaught,
    bypassing the restart trigger and leaving the agent wedged until backup SIGTERM hours later.
    """
    from core.loops import _run_messages_with_preempts

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    queue: asyncio.Queue = asyncio.Queue()

    async def cancel_side_effect(msg, *, state, config, is_user):
        raise asyncio.CancelledError

    with patch("core.loops.process_message", side_effect=cancel_side_effect):
        with pytest.raises(asyncio.CancelledError):
            await _run_messages_with_preempts(vm.QueuedTurn("msg", True, []), queue=queue, state=state, config=config)

    assert state.graceful_shutdown.is_set()
    assert state.persisted.last_restart_reason == "error: a turn was cancelled unexpectedly"


@pytest.mark.anyio
async def test_cancellation_during_shutdown_is_silent(tmp_path):
    """When the cancel arrives mid-process *while* shutdown is in progress, the inner handler must NOT log 'cancelled unexpectedly' or override restart_reason.

    Regression for a silent-death bug where shutdown-driven cancels were treated as crashes."""
    from core.loops import _run_messages_with_preempts

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    state.shutdown_event = asyncio.Event()
    queue: asyncio.Queue = asyncio.Queue()

    processing_started = asyncio.Event()

    async def hang(msg, *, state, config, is_user):
        processing_started.set()
        await asyncio.sleep(60)

    async def shutdown_and_cancel(task: asyncio.Task[None]) -> None:
        await processing_started.wait()
        state.shutdown_event.set()
        state.graceful_shutdown.set()
        task.cancel()

    with patch("core.loops.process_message", hang):
        task = asyncio.create_task(_run_messages_with_preempts(vm.QueuedTurn("msg", True, []), queue=queue, state=state, config=config))
        canceller = asyncio.create_task(shutdown_and_cancel(task))
        with pytest.raises(asyncio.CancelledError):
            await task
        await canceller

    assert state.persisted.last_restart_reason is None, "shutdown-driven cancel must not override restart_reason"


@pytest.mark.anyio
async def test_handle_processor_done_silent_cancel_triggers_restart(tmp_path):
    """Regression: a cancelled processor task used to return silently, leaving the agent wedged.
    Now it must log + set restart_reason + set graceful_shutdown."""
    from core.main import handle_processor_done

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()

    async def cancellable():
        await asyncio.sleep(10)

    task = asyncio.create_task(cancellable())
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    handle_processor_done(task, name="processor", state=state, config=config)

    assert state.graceful_shutdown.is_set()
    assert state.persisted.last_restart_reason == "crash: the processor was cancelled unexpectedly"


@pytest.mark.anyio
async def test_handle_processor_done_exception_triggers_restart(tmp_path):
    """A crashed processor task should log the exception and set restart_reason."""
    from core.main import handle_processor_done

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()

    async def crasher():
        raise RuntimeError("simulated crash")

    task = asyncio.create_task(crasher())
    with contextlib.suppress(RuntimeError):
        await task

    handle_processor_done(task, name="processor", state=state, config=config)

    assert state.graceful_shutdown.is_set()
    assert state.persisted.last_restart_reason is not None
    assert "RuntimeError" in state.persisted.last_restart_reason


@pytest.mark.anyio
async def test_handle_processor_done_silent_exit_triggers_restart(tmp_path):
    """A processor task that returns without error or cancellation should still trigger restart."""
    from core.main import handle_processor_done

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()

    async def silent():
        return None

    task = asyncio.create_task(silent())
    await task

    handle_processor_done(task, name="processor", state=state, config=config)

    assert state.graceful_shutdown.is_set()
    assert state.persisted.last_restart_reason == "crash: the processor exited silently"


@pytest.mark.anyio
async def test_handle_processor_done_noop_during_shutdown(tmp_path):
    """If shutdown was already initiated, the callback must not override the restart_reason."""
    from core.main import handle_processor_done

    config = cfg.VestaConfig(agent_dir=tmp_path / "agent")
    config.data_dir.mkdir(parents=True, exist_ok=True)
    state = vm.State()
    state.graceful_shutdown.set()
    state.persisted.last_restart_reason = "nightly: dreamer ran, session cleared for fresh context"

    async def silent():
        return None

    task = asyncio.create_task(silent())
    await task

    handle_processor_done(task, name="processor", state=state, config=config)

    assert state.persisted.last_restart_reason == "nightly: dreamer ran, session cleared for fresh context"


@pytest.mark.anyio
async def test_log_context_usage_timeout(tmp_path):
    """If get_context_usage hangs, log_context_usage must time out and not raise."""
    from core.diagnostics import log_context_usage

    state = vm.State()
    mock_client = MagicMock()

    async def hang_forever():
        await asyncio.sleep(10)
        return {"percentage": 0, "totalTokens": 0, "maxTokens": 0}

    mock_client.get_context_usage = hang_forever
    state.client = mock_client

    with patch("core.diagnostics._CONTEXT_USAGE_TIMEOUT_S", 0.05):
        await asyncio.wait_for(log_context_usage(state), timeout=0.2)


@pytest.mark.anyio
async def test_log_context_usage_emits_warning_event_once_on_crossing(tmp_path):
    """Crossing above the context warning threshold emits one error event; staying above does not re-emit."""
    from core.diagnostics import log_context_usage

    state = vm.State()
    state.event_bus = vm.EventBus(data_dir=tmp_path)
    queue = state.event_bus.subscribe()
    mock_client = MagicMock()
    pct = 92.0

    async def usage():
        return {"percentage": pct, "totalTokens": 184_000, "maxTokens": 200_000}

    mock_client.get_context_usage = usage
    state.client = mock_client

    def error_texts() -> list[str]:
        out: list[str] = []
        while not queue.empty():
            event = queue.get_nowait()
            if event["type"] == "error":
                out.append(event["text"])
        return out

    await log_context_usage(state)  # crosses into the warning band
    await log_context_usage(state)  # still above: must not re-emit

    errors = error_texts()
    assert len(errors) == 1, f"expected one context warning event, got {errors}"
    assert "above 80%" in errors[0]

    pct = 40.0
    await log_context_usage(state)  # drops back below: clears the flag, still no new event
    assert state.context_warning_active is False
    assert error_texts() == [], "dropping below threshold must not emit"
    state.event_bus.close()
