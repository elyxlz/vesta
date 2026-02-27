"""Vesta main entry point and orchestration."""

import asyncio
import signal

from rich import print_json

import vesta.models as vm
import vesta.core.effects as vfx
from vesta import logger
from vesta.core.init import init_skills, init_main_memory, init_prompts, init_skills_symlink, is_first_start
from vesta.core.io import input_handler, make_sigint_handler, make_sigterm_handler
from vesta.core.loops import message_processor, monitor_loop
from vesta.core.notifications import queue_greeting


async def run_vesta(config: vm.VestaConfig, *, state: vm.State, first_start: bool = False) -> None:
    state.shutdown_event = asyncio.Event()
    state.graceful_shutdown = asyncio.Event()

    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    signal.signal(signal.SIGINT, make_sigint_handler(state))
    signal.signal(signal.SIGTERM, make_sigterm_handler(state))

    logger.init("VESTA started")

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

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
    logger.shutdown("sweet dreams!")


def init_state(*, config: vm.VestaConfig) -> vm.State:
    session_id = config.session_file.read_text().strip() if config.session_file.exists() else None
    if session_id:
        logger.init(f"Resuming session {session_id[:16]}...")
    return vm.State(last_dreamer_run=vfx.get_current_time(), session_id=session_id)


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.state_dir, config.notifications_dir, config.logs_dir, config.data_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init("Vesta starting")

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
