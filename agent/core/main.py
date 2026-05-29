"""Vesta main entry point and orchestration."""

import asyncio
import errno
import os
import signal
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
    drop_greeting_notification,
    message_processor,
    monitor_loop,
)
from .migrations import drop_pending_migrations

SignalHandler = tp.Callable[[int, types.FrameType | None], None]


async def input_handler(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State) -> None:
    while not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput("")
            if state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            logger.user(user_msg.strip())
            await queue.put((user_msg.strip(), True))
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


def _make_signal_handler(state: vm.State, *, allow_force_exit: bool = False) -> SignalHandler:
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
    if state.shutdown_event.is_set() or state.graceful_shutdown.is_set():
        return
    if task.cancelled():
        logger.error("message_processor cancelled unexpectedly — restarting")
        state.persisted.last_restart_reason = "crash — processor cancelled unexpectedly"
    else:
        exc = task.exception()
        if exc is not None:
            exit_code, stderr_tail = format_crash_detail(exc, state.stderr_buffer)
            logger.error(f"message_processor crashed: {type(exc).__name__}: {exc} | exit_code={exit_code}\nRecent stderr:\n{stderr_tail}")
            state.persisted.last_restart_reason = f"crash — {type(exc).__name__}: {exc}"
        else:
            logger.error("message_processor exited without error — restarting")
            state.persisted.last_restart_reason = "crash — processor exited silently"
    state_store.save_state(state.persisted, config)
    state.graceful_shutdown.set()


async def run_vesta(config: vm.VestaConfig, *, state: vm.State, first_start: bool = False, restart_reason: str = vm.CLEAN_RESTART) -> None:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, _make_signal_handler(state, allow_force_exit=True))
    signal.signal(signal.SIGTERM, _make_signal_handler(state))

    logger.init(f"{config.agent_name.upper()} started")

    if config.agent_provider == "openrouter":
        from .openrouter_proxy import start_proxy

        state.openrouter_runner, proxy_port = await start_proxy(zdr=config.openrouter_zdr)
        # Pass the proxy URL into ClaudeAgentOptions.env (build_client_options reads
        # this) instead of mutating os.environ — otherwise every subprocess we spawn
        # inherits ANTHROPIC_BASE_URL and silently routes through the OpenRouter proxy.
        state.openrouter_base_url = f"http://127.0.0.1:{proxy_port}"
        logger.init(f"OpenRouter proxy on 127.0.0.1:{proxy_port} (ZDR {'on' if config.openrouter_zdr else 'off'})")

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    drop_pending_migrations(state=state, config=config, first_start=first_start)
    greeting_reason = "first_start" if first_start else restart_reason
    drop_greeting_notification(config=config, state=state, reason=greeting_reason)

    # First-start defers WS until the agent calls `mark_setup_done` (the readiness signal vestad polls).
    # Every other boot binds WS immediately so restart greetings that poll the WS port don't deadlock.
    if not first_start:
        state.ws_runner = await start_ws_server(state.event_bus, config)
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

    if not state.shutdown_event.is_set():
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
    if state.openrouter_runner is not None:
        await state.openrouter_runner.cleanup()
    state.event_bus.close()
    logger.shutdown("sweet dreams!")


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

    event_bus = EventBus(data_dir=config.data_dir)
    return vm.State(persisted=persisted, event_bus=event_bus)


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.agent_dir, config.notifications_dir, config.logs_dir, config.data_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init(f"{config.agent_name} starting")

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
