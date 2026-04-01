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
from vesta.core.history import open_history
from vesta.core.init import get_memory_path
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

            await queue.put((user_msg.strip(), True))
        except (KeyboardInterrupt, EOFError):
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
        state.shutdown_count += 1
        if state.shutdown_count == 1:
            state.graceful_shutdown.set()
        elif allow_force_exit and state.shutdown_count > 2:
            os._exit(0)
        else:
            state.shutdown_event.set()

    return handler


async def run_vesta(config: vm.VestaConfig, *, state: vm.State, first_start: bool = False, crashed: bool = False) -> None:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, _make_signal_handler(state, allow_force_exit=True))
    signal.signal(signal.SIGTERM, _make_signal_handler(state))

    logger.init(f"{config.agent_name.upper()} started")
    (config.data_dir / "run_marker").touch()

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    # Bridge logger -> event bus so log panel mirrors console
    from vesta.events import LogEvent

    def _log_sink(text: str, category: str) -> None:
        state.event_bus.emit(LogEvent(type="log", text=text, category=category))

    logger.set_event_sink(_log_sink)

    ws_runner = await start_ws_server(state.event_bus, message_queue, state, config)
    logger.init(f"WebSocket server started on port {config.ws_port}")

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state=state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
    ]

    reason = "first_start" if first_start else ("crash — restarted after unexpected exit" if crashed else "restart — clean restart")
    await queue_greeting(message_queue, config=config, reason=reason)

    try:
        await state.graceful_shutdown.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        state.shutdown_event.set()

    if not state.shutdown_event.is_set():
        state.shutdown_event.set()

    logger.shutdown("Shutting down...")

    for task in tasks:
        task.cancel()

    _, pending = await asyncio.wait(tasks, timeout=5)
    if pending:
        logger.shutdown("Shutdown timed out (SDK cleanup hung), forcing exit")
        os._exit(1)
    await ws_runner.cleanup()
    (config.data_dir / "run_marker").unlink(missing_ok=True)
    logger.shutdown("sweet dreams!")


def _detect_crash(config: vm.VestaConfig) -> bool:
    run_marker = config.data_dir / "run_marker"
    crashed = run_marker.exists()
    run_marker.unlink(missing_ok=True)
    return crashed


def _read_last_dreamer_run(config: vm.VestaConfig) -> dt.datetime | None:
    path = config.data_dir / "last_dreamer_run"
    try:
        if path.exists():
            return dt.datetime.fromisoformat(path.read_text().strip())
    except (OSError, ValueError, UnicodeDecodeError):
        logger.warning("Could not read last_dreamer_run file")
    return None


def init_state(*, config: vm.VestaConfig) -> tuple[vm.State, bool]:
    session_id = None
    try:
        if config.session_file.exists():
            session_id = config.session_file.read_text().strip() or None
    except (OSError, UnicodeDecodeError):
        logger.warning("Could not read session file, starting fresh")

    crashed = _detect_crash(config)
    if crashed:
        logger.init("Crash detected")

    last_dreamer_run = _read_last_dreamer_run(config)

    if session_id:
        logger.init(f"Resuming session {session_id[:16]}...")
    return vm.State(last_dreamer_run=last_dreamer_run, session_id=session_id), crashed


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.root, config.notifications_dir, config.logs_dir, config.data_dir, config.dreamer_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init(f"{config.agent_name} starting")

    memory_path = get_memory_path(config)
    try:
        first_start = not memory_path.exists() or "[Unknown - need to ask]" in memory_path.read_text()
    except (OSError, UnicodeDecodeError):
        first_start = True
    initial_state, crashed = init_state(config=config)
    initial_state.history = open_history(config.history_db)
    logger.init("Starting main loop...")
    await run_vesta(config, state=initial_state, first_start=first_start, crashed=crashed)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error")


if __name__ == "__main__":
    main()
