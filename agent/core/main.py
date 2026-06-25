"""Vesta main entry point and orchestration."""

import asyncio
import errno
import os
import signal
import tomllib
import types
import typing as tp

import aioconsole
from rich import print_json

from . import models as vm
from . import logger
from . import state_store
from .api import start_ws_server
from .diagnostics import format_crash_detail
from .loops import (
    drop_core_notification,
    drop_greeting_notification,
    message_processor,
    monitor_loop,
)
from .default_skills import reconcile_default_skills
from .migrations import drop_pending_migrations


async def input_handler(queue: asyncio.Queue[tuple[str, bool, list[str]]], *, state: vm.State) -> None:
    while not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput("")
            if state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            logger.user(user_msg.strip())
            await queue.put((user_msg.strip(), True, []))
        except KeyboardInterrupt:
            logger.shutdown("stdin: KeyboardInterrupt, shutting down")
            state.shutdown_event.set()
            break
        except EOFError:
            logger.shutdown("stdin: EOF (no TTY?), shutting down")
            state.shutdown_event.set()
            break
        except asyncio.CancelledError:
            break
        except BlockingIOError:
            await asyncio.sleep(0.1)
            continue
        except OSError as e:
            if e.errno == errno.EAGAIN or e.errno == errno.EWOULDBLOCK:
                await asyncio.sleep(0.1)
                continue
            else:
                raise


def _make_signal_handler(state: vm.State, *, allow_force_exit: bool = False) -> tp.Callable[[int, types.FrameType | None], None]:
    def handler(signum: int, frame: types.FrameType | None) -> None:
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


def handle_processor_done(task: asyncio.Task[None], *, state: vm.State, config: vm.VestaConfig) -> None:
    """Set restart_reason + graceful_shutdown on unexpected termination so the agent never wedges silently."""
    if state.graceful_shutdown.is_set():
        return
    if task.cancelled():
        logger.error("message_processor cancelled unexpectedly, restarting")
        state.persisted.last_restart_reason = "crash: processor cancelled unexpectedly"
    else:
        exc = task.exception()
        if exc is not None:
            exit_code, stderr_tail = format_crash_detail(exc, state.stderr_buffer)
            logger.error(f"message_processor crashed: {type(exc).__name__}: {exc} | exit_code={exit_code}\nRecent stderr:\n{stderr_tail}")
            state.persisted.last_restart_reason = f"crash: {type(exc).__name__}: {exc}"
        else:
            logger.error("message_processor exited without error, restarting")
            state.persisted.last_restart_reason = "crash: processor exited silently"
    state_store.save_state(state.persisted, config)
    state.graceful_shutdown.set()


async def run_vesta(config: vm.VestaConfig, *, state: vm.State, first_start: bool = False, restart_reason: str = vm.CLEAN_RESTART) -> None:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, _make_signal_handler(state, allow_force_exit=True))
    signal.signal(signal.SIGTERM, _make_signal_handler(state))

    logger.init(f"{config.agent_name.upper()} started")

    message_queue: asyncio.Queue[tuple[str, bool, list[str]]] = asyncio.Queue()

    drop_pending_migrations(state=state, config=config, first_start=first_start)
    reconcile_default_skills(config=config, first_start=first_start)
    greeting_reason = "first_start" if first_start else restart_reason
    drop_greeting_notification(config=config, state=state, reason=greeting_reason)

    # Bind the HTTP/WS server on every boot, including first start. vestad reaches
    # GET/PUT /config over this port to read auth state and deliver credentials, so a
    # fresh unauthenticated agent must be reachable before the first_start_setup
    # conversation (which itself needs a provider) can run.
    state.ws_runner = await start_ws_server(state.event_bus, config, state)
    logger.init(f"WebSocket server started on port {config.ws_port}")

    processor_task = asyncio.create_task(message_processor(message_queue, state=state, config=config))
    processor_task.add_done_callback(lambda t: handle_processor_done(t, state=state, config=config))

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        processor_task,
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
    ]

    try:
        await state.graceful_shutdown.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        state.shutdown_event.set()

    state.shutdown_event.set()

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


def _report_config_issues(issues: list[str], *, config: vm.VestaConfig) -> None:
    """Surface config vars that failed validation: log them and tell the agent via a core
    notification so it can flag the bad values to the user, since the agent ran with defaults."""
    if not issues:
        return
    for issue in issues:
        logger.error(f"Invalid config, using default: {issue}")
    body = (
        "Some configuration env vars failed to validate and were reverted to their defaults. "
        "Let the user know so they can fix the values in ~/.bashrc and run restart_vesta:\n" + "\n".join(f"- {issue}" for issue in issues)
    )
    drop_core_notification(type_=vm.TYPE_CONFIG_INVALID, body=body, interrupt=False, config=config)


def _consume_restart_reason(state: vm.State, config: vm.VestaConfig, *, first_start: bool) -> str:
    """Return the reason to log for this boot and clear it from persisted state. On a never-run agent the absence of a stored reason is innocent; report FIRST_START_REASON instead of a misleading crash label."""
    if first_start:
        return vm.FIRST_START_REASON
    stored = state.persisted.last_restart_reason
    state.persisted.last_restart_reason = None
    state_store.save_state(state.persisted, config)
    return stored or vm.CRASH_RESTART


def init_state(*, config: vm.VestaConfig) -> vm.State:
    persisted = state_store.load_state(config)
    if persisted.session_id:
        logger.init(f"Resuming session {persisted.session_id[:16]}...")
    from .events import EventBus
    from .provider import derive_status

    event_bus = EventBus(data_dir=config.data_dir)
    provider_status = derive_status(config)
    logger.init(f"Provider: {provider_status.kind} ({provider_status.state.value})")
    return vm.State(persisted=persisted, event_bus=event_bus, provider_status=provider_status)


def _vesta_version(*, config: vm.VestaConfig) -> str:
    """Version of the code actually running, read from the bind-mounted pyproject.toml (re-extracted
    on upgrade, so it tracks the running core). Best-effort: never block startup over a version label."""
    pyproject = config.agent_dir / "pyproject.toml"
    if not pyproject.exists():
        return "unknown"
    try:
        return tomllib.loads(pyproject.read_text())["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, OSError) as e:
        logger.init(f"could not read version: {e}")
        return "unknown"


async def async_main() -> None:
    config, config_issues = vm.load_config()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.agent_dir, config.notifications_dir, config.logs_dir, config.data_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    # seed_context (one-shot setup notes) is delivered through the config store; materialize it to the
    # file the first-wake prompt reads. Only when absent, so a re-delivery never clobbers notes the
    # agent already consumed.
    seed_path = config.data_dir / "seed-context.md"
    if config.seed_context and not seed_path.exists():
        seed_path.write_text(config.seed_context)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init(f"{config.agent_name} starting on vesta v{_vesta_version(config=config)}")
    _report_config_issues(config_issues, config=config)

    # Converge a legacy agent's env-based preferences into the writable config store, so the whole
    # fleet ends up on the new config system. Idempotent and safe (see migrate_legacy_config_to_store).
    vm.migrate_legacy_config_to_store()

    initial_state = init_state(config=config)
    first_start = not initial_state.persisted.first_start_done
    restart_reason = _consume_restart_reason(initial_state, config, first_start=first_start)
    logger.init(f"Starting main loop ({restart_reason})...")
    await run_vesta(config, state=initial_state, first_start=first_start, restart_reason=restart_reason)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error")


if __name__ == "__main__":
    main()
