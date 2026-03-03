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
from vesta.core.init import init_skills, init_main_memory, init_prompts, init_skills_symlink, is_first_start
from vesta.core.loops import message_processor, monitor_loop, queue_greeting

SignalHandler = tp.Callable[[int, types.FrameType | None], None]


async def input_handler(queue: asyncio.Queue[tuple[str, bool]], *, state: vm.State) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            user_msg = await aioconsole.ainput("")
            if state.shutdown_event and state.shutdown_event.is_set():
                break
            if not user_msg.strip():
                continue

            logger.user(user_msg.strip())
            await queue.put((user_msg.strip(), True))
        except (KeyboardInterrupt, EOFError):
            if state.shutdown_event:
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
            if state.graceful_shutdown:
                state.graceful_shutdown.set()
        elif allow_force_exit and state.shutdown_count > 2:
            os._exit(0)
        else:
            if state.shutdown_event:
                state.shutdown_event.set()

    return handler


async def run_vesta(config: vm.VestaConfig, *, state: vm.State, first_start: bool = False) -> None:
    state.shutdown_event = asyncio.Event()
    state.graceful_shutdown = asyncio.Event()

    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, _make_signal_handler(state, allow_force_exit=True))
    signal.signal(signal.SIGTERM, _make_signal_handler(state))

    logger.init(f"{config.agent_name.upper()} started")
    (config.data_dir / "run_marker").touch()

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    ws_runner = await start_ws_server(state.event_bus, message_queue, state, config)
    logger.init(f"WebSocket server started on port {config.ws_port}")

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state=state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
    ]

    await queue_greeting(message_queue, config=config, first_start=first_start)

    try:
        await state.graceful_shutdown.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        state.shutdown_event.set()

    if not state.shutdown_event.is_set():
        state.shutdown_event.set()

    logger.shutdown("Shutting down...")

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    await ws_runner.cleanup()
    (config.data_dir / "run_marker").unlink(missing_ok=True)
    logger.shutdown("sweet dreams!")


def _detect_crash(config: vm.VestaConfig) -> str | None:
    crash_reason = config.data_dir / "crash_reason"
    run_marker = config.data_dir / "run_marker"

    context = None
    if crash_reason.exists():
        reason = crash_reason.read_text().strip()
        crash_reason.unlink(missing_ok=True)
        context = f"[System: Restarted after forced exit. Reason: {reason}]"
    elif run_marker.exists():
        context = "[System: Restarted after unexpected crash.]"

    run_marker.unlink(missing_ok=True)
    return context


def init_state(*, config: vm.VestaConfig) -> vm.State:
    session_id = None
    try:
        if config.session_file.exists():
            session_id = config.session_file.read_text().strip() or None
    except (OSError, UnicodeDecodeError):
        logger.warning("Could not read session file, starting fresh")

    pending_context = _detect_crash(config)
    if pending_context:
        logger.init(f"Crash detected: {pending_context}")

    if session_id:
        logger.init(f"Resuming session {session_id[:16]}...")
    return vm.State(last_dreamer_run=dt.datetime.now(), session_id=session_id, pending_context=pending_context)


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.state_dir, config.notifications_dir, config.logs_dir, config.data_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init(f"{config.agent_name} starting")

    first_start = is_first_start(config)
    logger.init("Initializing memory...")
    init_main_memory(config)
    init_prompts(config)
    logger.init("Initializing skills...")
    init_skills(config)
    init_skills_symlink(config)

    initial_state = init_state(config=config)
    logger.init("Starting main loop...")
    await run_vesta(config, state=initial_state, first_start=first_start)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error")


if __name__ == "__main__":
    main()
