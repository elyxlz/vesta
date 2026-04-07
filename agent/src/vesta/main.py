"""Vesta main entry point and orchestration."""

import asyncio
import datetime as dt
import errno
import os
import signal
import types
import typing as tp

import aioconsole
from rich import print_json

import vesta.models as vm
from vesta import logger
from vesta.api import start_ws_server
from vesta.core.loops import message_processor, monitor_loop, queue_greeting

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


CLEAN_RESTART = "restart — clean restart"


async def run_vesta(config: vm.VestaConfig, *, state: vm.State, first_start: bool = False, restart_reason: str = CLEAN_RESTART) -> None:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, _make_signal_handler(state, allow_force_exit=True))
    signal.signal(signal.SIGTERM, _make_signal_handler(state))

    logger.init(f"{config.agent_name.upper()} started")

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    ws_runner = await start_ws_server(state.event_bus, config)
    logger.init(f"WebSocket server started on port {config.ws_port}")

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state=state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
    ]

    greeting_reason = "first_start" if first_start else restart_reason
    await queue_greeting(message_queue, config=config, reason=greeting_reason)

    try:
        await state.graceful_shutdown.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        state.shutdown_event.set()

    if not state.shutdown_event.is_set():
        state.shutdown_event.set()

    reason = state.restart_reason or CLEAN_RESTART
    logger.shutdown(f"Shutting down ({reason})")
    _write_restart_reason(config, state.restart_reason or CLEAN_RESTART)

    for task in tasks:
        task.cancel()

    _, pending = await asyncio.wait(tasks, timeout=5)
    if pending:
        logger.shutdown("Shutdown timed out (SDK cleanup hung), forcing exit")
        os._exit(1)
    await ws_runner.cleanup()
    state.event_bus.close()
    logger.shutdown("sweet dreams!")


def _write_restart_reason(config: vm.VestaConfig, reason: str) -> None:
    try:
        (config.data_dir / "restart_reason").write_text(reason)
    except OSError:
        logger.warning("Could not write restart_reason file")


def _read_restart_reason(config: vm.VestaConfig) -> str:
    path = config.data_dir / "restart_reason"
    try:
        reason = path.read_text().strip()
        path.unlink(missing_ok=True)
        return reason
    except FileNotFoundError:
        return "crash — restarted after unexpected exit"
    except (OSError, UnicodeDecodeError):
        logger.warning("Could not read restart_reason file")
        return "crash — restarted after unexpected exit"


def _read_last_dreamer_run(config: vm.VestaConfig) -> dt.datetime | None:
    path = config.data_dir / "last_dreamer_run"
    try:
        if path.exists():
            return dt.datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("Could not read last_dreamer_run file")
    return None


def init_state(*, config: vm.VestaConfig) -> vm.State:
    session_id = None
    try:
        if config.session_file.exists():
            session_id = config.session_file.read_text().strip() or None
    except (OSError, UnicodeDecodeError):
        logger.warning("Could not read session file, starting fresh")

    last_dreamer_run = _read_last_dreamer_run(config)

    if session_id:
        logger.init(f"Resuming session {session_id[:16]}...")
    from vesta.events import EventBus

    event_bus = EventBus(data_dir=config.data_dir)
    return vm.State(last_dreamer_run=last_dreamer_run, session_id=session_id, event_bus=event_bus)


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.root, config.notifications_dir, config.logs_dir, config.data_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init(f"{config.agent_name} starting")

    restart_reason = _read_restart_reason(config)
    initial_state = init_state(config=config)
    first_start_marker = config.data_dir / "first_start_done"
    first_start = not first_start_marker.exists()
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
