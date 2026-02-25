"""Vesta main entry point and orchestration."""

import asyncio
import signal

from rich import print_json

import vesta.models as vm
import vesta.core.effects as vfx
from vesta import logger
from vesta.core.init import init_skills, init_main_memory, init_skills_symlink
from vesta.core.io import input_handler, make_signal_handler
from vesta.core.loops import message_processor, monitor_loop
from vesta.core.notifications import maybe_enqueue_whatsapp_greeting


async def run_vesta(config: vm.VestaConfig, *, state: vm.State) -> None:
    state.shutdown_event = asyncio.Event()

    handler = make_signal_handler(state)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    logger.init("VESTA started")

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state=state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
    ]

    await maybe_enqueue_whatsapp_greeting(message_queue, config=config)

    try:
        await state.shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        state.shutdown_event.set()

    logger.shutdown("Shutting down...")

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.shutdown("sweet dreams!")


def init_state(*, config: vm.VestaConfig) -> vm.State:
    return vm.State(last_memory_consolidation=vfx.get_current_time())


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.init("Config:")
    print_json(data=config.model_dump(mode="json"))

    for path in [config.state_dir, config.notifications_dir, config.logs_dir, config.data_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, log_level=config.log_level)
    logger.init("Vesta starting")

    logger.init("Initializing memory...")
    init_main_memory(config)
    logger.init("Initializing skills...")
    init_skills(config)
    init_skills_symlink(config)

    initial_state = init_state(config=config)
    logger.init("Starting main loop...")
    await run_vesta(config, state=initial_state)


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error")


if __name__ == "__main__":
    main()
