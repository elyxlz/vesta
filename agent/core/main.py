"""Vesta main entry point and orchestration."""

import asyncio
import os
import signal
import sys
import time
import types
import typing as tp

from rich import print_json

from . import config as cfg
from . import logger, state_store
from . import models as vm
from .api import start_ws_server
from .claude_runtime import reconcile_claude_runtime
from .diagnostics import format_crash_detail
from .events import EventBus
from .loops import (
    greeting_turn,
    message_processor,
    monitor_loop,
)
from .migrations import pending_migration_turns
from .provider import derive_status, enforce_active_credentials
from .upstream_sync import upstream_sync_turn, vesta_version


def _make_signal_handler(state: vm.State, *, allow_force_exit: bool = False) -> tp.Callable[[int, types.FrameType | None], None]:
    def handler(signum: int, _frame: types.FrameType | None) -> None:
        sig_name = signal.Signals(signum).name
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            logger.shutdown(f"received {sig_name}, graceful shutdown")
            state.graceful_shutdown.set()
        elif allow_force_exit and state.shutdown_count > 2:
            logger.shutdown(f"received {sig_name} x{state.shutdown_count}, force exit")
            os._exit(0)
        else:
            logger.shutdown(f"received {sig_name} x{state.shutdown_count}, immediate shutdown")
            state.shutdown_event.set()

    return handler


def handle_processor_done(task: asyncio.Task[None], *, name: str, state: vm.State, config: cfg.VestaConfig) -> None:
    """Set restart_reason + graceful_shutdown on unexpected termination so the agent never wedges silently."""
    if state.graceful_shutdown.is_set():
        return
    if task.cancelled():
        logger.error(f"{name} cancelled unexpectedly, restarting")
        state.persisted.last_restart_reason = f"crash: the {name} was cancelled unexpectedly"
    else:
        exc = task.exception()
        if exc is not None:
            exit_code, stderr_tail = format_crash_detail(exc, state.stderr_buffer)
            logger.error(f"{name} crashed: {type(exc).__name__}: {exc} | exit_code={exit_code}\nRecent stderr:\n{stderr_tail}")
            state.persisted.last_restart_reason = f"crash: {type(exc).__name__}: {exc}"
        else:
            logger.error(f"{name} exited without error, restarting")
            state.persisted.last_restart_reason = f"crash: the {name} exited silently"
    state_store.save_state(state.persisted, config)
    state.graceful_shutdown.set()


async def run_vesta(
    config: cfg.VestaConfig,
    *,
    state: vm.State,
    first_start: bool = False,
    restart_reason: str = vm.CLEAN_RESTART,
    config_issues: list[str] | None = None,
) -> bool:
    """Run the agent until shutdown. Returns whether the agent is exiting because it crashed, so the
    entry point can exit non-zero and let Docker's on-failure policy recover it (intentional
    restarts/stops are vestad-driven and return False)."""
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, _make_signal_handler(state, allow_force_exit=True))
    signal.signal(signal.SIGTERM, _make_signal_handler(state))

    logger.init(f"{config.agent_name.upper()} started")

    message_queue: asyncio.Queue[vm.QueuedTurn] = asyncio.Queue()

    # Boot-time control-flow runs as boot turns: enqueued first (before the processor/input/monitor
    # tasks start), processed immediately and non-interruptibly so the agent converges and orients
    # before taking any other work.
    greeting_reason = "first_start" if first_start else restart_reason
    for body in collect_boot_turns(
        state=state, config=config, config_issues=config_issues or [], greeting_reason=greeting_reason, first_start=first_start
    ):
        await message_queue.put(vm.QueuedTurn(body, False, [], interruptible=False))

    # Bind the HTTP/WS server on every boot, including first start. vestad reaches
    # GET/PUT /config over this port to read auth state and deliver credentials, so a
    # fresh unauthenticated agent must be reachable before the birth
    # conversation (which itself needs a provider) can run.
    state.ws_runner = await start_ws_server(state.event_bus, config, state)
    logger.init(f"WebSocket server started on port {config.ws_port}")

    processor_task = asyncio.create_task(message_processor(message_queue, state=state, config=config))
    processor_task.add_done_callback(lambda t: handle_processor_done(t, name="message processor", state=state, config=config))

    monitor_task = asyncio.create_task(monitor_loop(message_queue, state=state, config=config))
    monitor_task.add_done_callback(lambda t: handle_processor_done(t, name="notification monitor", state=state, config=config))

    tasks = [processor_task, monitor_task]

    try:
        await state.graceful_shutdown.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        state.shutdown_event.set()

    state.shutdown_event.set()

    # A crash (set by the processor/loop error handlers) must exit non-zero so Docker's on-failure
    # policy recovers us. Intentional restarts/stops are driven by vestad (docker restart/stop) and
    # a SIGTERM-driven shutdown carries no crash reason, so those exit 0 — vestad starts us back, or
    # leaves us down. Capture intent before the clean-restart default below overwrites a blank reason.
    crashed = vm.is_crash_reason(state.persisted.last_restart_reason)
    reason = state.persisted.last_restart_reason or vm.CLEAN_RESTART
    logger.shutdown(f"Shutting down ({reason})")
    if not state.persisted.last_restart_reason:
        state.persisted.last_restart_reason = vm.CLEAN_RESTART
        state_store.save_state(state.persisted, config)

    for task in tasks:
        task.cancel()

    _, pending = await asyncio.wait(tasks, timeout=5)
    if pending:
        logger.shutdown("Shutdown timed out (SDK cleanup hung), forcing exit")
        os._exit(1)
    if state.ws_runner is not None:
        await state.ws_runner.cleanup()
    if state.cache_proxy_runner is not None:
        await state.cache_proxy_runner.cleanup()
    state.event_bus.close()
    logger.shutdown("sweet dreams!")
    return crashed


def config_issues_turn(issues: list[str]) -> str | None:
    """Surface config vars that failed validation: log them and return a boot-turn body telling the
    agent to flag the bad values to the user (the agent ran with defaults), or None when clean."""
    if not issues:
        return None
    for issue in issues:
        logger.error(f"Invalid config, using default: {issue}")
    return (
        "Some configuration env vars failed to validate and were reverted to their defaults. "
        "Let the user know so they can fix the values in ~/.bashrc and run restart_vesta:\n" + "\n".join(f"- {issue}" for issue in issues)
    )


# A migration/upgrade boot is a restart: the daemons are down, but the converge turns (migrations,
# upstream sync) run before the greeting's restart turn, so nothing has restored them yet. Prepend
# this to the first converge turn so the agent runs the restart skill first, exactly as it would on
# a plain restart, before tunnelling into the migration or upgrade.
BOOT_RESTORE_ORIENTATION = (
    "Your daemons are down after this boot, just like any restart. Before the task below, read the "
    "`restart` skill and run its daemon guard block to bring your daemons back (it is idempotent, so "
    "running it when everything is already up is a safe no-op). Then continue with the task."
)


def collect_boot_turns(
    *, state: vm.State, config: cfg.VestaConfig, config_issues: list[str], greeting_reason: str, first_start: bool
) -> list[str]:
    """Boot-time control-flow as ordered prompt bodies: migrations, then upstream sync, then
    config issues, then the greeting last — converge first, orient and reach out last. Each is
    delivered as a boot turn (immediate, non-interruptible), not a notification.
    The greeting's restart turn restores daemons; converge turns run before it, so the first one carries
    BOOT_RESTORE_ORIENTATION to restore daemons first."""
    turns: list[str] = []
    turns.extend(pending_migration_turns(state=state, config=config, first_start=first_start))
    sync_turn = upstream_sync_turn(state=state, config=config, first_start=first_start)
    if sync_turn is not None:
        turns.append(sync_turn)
    config_turn = config_issues_turn(config_issues)
    if config_turn is not None:
        turns.append(config_turn)
    if turns:
        turns[0] = f"{BOOT_RESTORE_ORIENTATION}\n\n{turns[0]}"
    greeting = greeting_turn(config=config, state=state, reason=greeting_reason)
    if greeting is not None:
        turns.append(greeting)
    return turns


def _consume_restart_reason(state: vm.State, config: cfg.VestaConfig, *, first_start: bool) -> str:
    """Return the reason to log for this boot and clear it from persisted state. On a never-run agent
    the absence of a stored reason is innocent; report FIRST_START_REASON instead of a misleading
    crash label."""
    # Drain the inbox on every boot, including first start: a file left behind would fire stale
    # on some later, unrelated boot.
    pending = state_store.take_pending_reason(config)
    if first_start:
        return vm.FIRST_START_REASON
    stored = state.persisted.last_restart_reason
    if pending is not None and not vm.is_crash_reason(stored):
        # An external actor (vestad backup/mounts/manual restart) handed in a reason for this boot.
        # It overrides the clean-restart placeholder the prior run persisted on its way down, but
        # never a recorded crash: the crash detail is the more important story to surface.
        stored = pending
    state.persisted.last_restart_reason = None
    state_store.save_state(state.persisted, config)
    return stored or vm.CRASH_RESTART


def init_state(*, config: cfg.VestaConfig) -> vm.State:
    persisted = state_store.load_state(config)
    if persisted.session_id:
        logger.init(f"Resuming session {persisted.session_id[:16]}...")
    event_bus = EventBus(data_dir=config.data_dir)
    provider_status = derive_status(config)
    logger.init(f"Provider: {provider_status.kind} ({provider_status.state.value})")
    return vm.State(persisted=persisted, event_bus=event_bus, provider_status=provider_status)


async def async_main() -> bool:
    config, config_issues = cfg.load_config()
    # Apply the configured timezone to the process once, here at the entry point, so every consumer
    # (shell `date`, calendar/reminders skills, tasks' tzlocal) inherits it. Config is inert data:
    # a PUT /config timezone change applies on the next restart, never mid-request.
    os.environ["TZ"] = config.timezone
    time.tzset()

    for path in [config.agent_dir, config.notifications_dir, config.logs_dir, config.data_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    reconcile_claude_runtime(config)
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    # seed_context (one-shot setup notes) is delivered through the config store; materialize it to the
    # file the first-wake prompt reads. Only when absent, so a re-delivery never clobbers notes the
    # agent already consumed.
    seed_path = config.data_dir / "seed-context.md"
    if config.seed_context and not seed_path.exists():
        seed_path.write_text(config.seed_context)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init(f"{config.agent_name} starting on vesta v{vesta_version(config)}")
    # A previous harness may have refreshed its token after sign-in but before vestad stopped it.
    # Boot is the final enforcement point; the helper cross-checks the raw store before deleting.
    enforce_active_credentials(config)

    initial_state = init_state(config=config)
    first_start = not initial_state.persisted.first_start_done
    restart_reason = _consume_restart_reason(initial_state, config, first_start=first_start)
    logger.init(f"Starting main loop ({restart_reason})...")
    return await run_vesta(config, state=initial_state, first_start=first_start, restart_reason=restart_reason, config_issues=config_issues)


def main() -> None:
    crashed = False
    try:
        crashed = asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error")
        crashed = True
    # Exit non-zero on a crash so Docker's on-failure policy restarts the container; a clean or
    # vestad-driven shutdown exits 0 (the container stays down unless vestad starts it back).
    if crashed:
        sys.exit(1)


if __name__ == "__main__":
    main()
