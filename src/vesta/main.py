"""Vesta main entry point and orchestration."""

import asyncio
import shutil
import signal

import vesta.models as vm
import vesta.core.effects as vfx
from vesta import logger
from vesta.config import Messages
from vesta.integrations import onedrive as vod
from vesta.integrations.mcp_registry import build_mcp_servers
from vesta.core.init import init_skills, init_main_memory, init_dreamer_prompt
from vesta.core.io import input_handler, make_signal_handler
from vesta.core.client import create_claude_client
from vesta.core.loops import message_processor, monitor_loop
from vesta.core.dreamer import preserve_memory
from vesta.core.notifications import maybe_enqueue_whatsapp_greeting


async def graceful_shutdown(state: vm.State, *, config: vm.VestaConfig) -> None:
    logger.info("=== Vesta shutting down ===")

    await preserve_memory(state, config=config)

    if state.client:
        await state.client.__aexit__(None, None, None)

    if config.onedrive_dir.exists() and config.onedrive_token:
        vod.unmount_onedrive(config.onedrive_dir)

    logger.info(Messages.SHUTDOWN_COMPLETE)


async def log_startup_info(config: vm.VestaConfig) -> None:
    logger.info("VESTA started")
    mcps = build_mcp_servers(config)
    if mcps:
        logger.info(f"Active MCPs: {', '.join(mcps.keys())}")


async def run_vesta(config: vm.VestaConfig, *, state: vm.State) -> None:
    state.shutdown_event = asyncio.Event()

    handler = make_signal_handler(state)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    await log_startup_info(config)

    message_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()

    tasks = [
        asyncio.create_task(input_handler(message_queue, state=state)),
        asyncio.create_task(message_processor(message_queue, state=state, config=config)),
        asyncio.create_task(monitor_loop(message_queue, state=state, config=config)),
    ]

    await maybe_enqueue_whatsapp_greeting(message_queue, config=config)

    try:
        if state.shutdown_event:
            await state.shutdown_event.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        if state.shutdown_event:
            state.shutdown_event.set()

    logger.info(Messages.SHUTDOWN_INITIATED)

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)

    try:
        await asyncio.wait_for(graceful_shutdown(state, config=config), timeout=config.shutdown_timeout)
    except TimeoutError:
        logger.error("Shutdown timeout")


def check_dependencies() -> None:
    if shutil.which("npm") is None:
        raise RuntimeError("npm is not found in PATH. Please install Node.js and npm: https://nodejs.org/")

    if shutil.which("node") is None:
        raise RuntimeError("node is not found in PATH. Please install Node.js: https://nodejs.org/")

    if shutil.which("uv") is None:
        raise RuntimeError("uv is not found in PATH. Please install uv: https://docs.astral.sh/uv/getting-started/installation/")

    if shutil.which("go") is None:
        raise RuntimeError("go is not found in PATH. Please install Go: https://go.dev/doc/install")

    if not vod.check_rclone_installed():
        raise RuntimeError("rclone is not found in PATH. Please install rclone: https://rclone.org/install/")


async def init_state(*, config: vm.VestaConfig) -> vm.State:
    now = vfx.get_current_time()
    state = vm.State(
        client=None,
        shutdown_event=None,
        shutdown_count=0,
        is_processing=False,
        sub_agent_context=None,
        session_id=None,
        pending_system_message=None,
        last_memory_consolidation=now,
    )
    state.client = await create_claude_client(config, state=state)
    return state


async def async_main() -> None:
    config = vm.VestaConfig()
    logger.info(f"Config: {config.model_dump(mode='json')}")

    for path in [config.state_dir, config.notifications_dir, config.logs_dir, config.data_dir]:
        path.mkdir(parents=True, exist_ok=True)

    logger.setup(config.logs_dir, debug=config.debug)
    logger.info("=== Vesta starting ===")

    init_main_memory(config)
    init_dreamer_prompt(config)
    init_skills(config)

    if config.onedrive_token:
        logger.info("Setting up OneDrive mount...")
        vod.unmount_onedrive(config.onedrive_dir)
        vod.setup_rclone_config(config, config_path=config.rclone_config_file)
        await vod.mount_onedrive(config, mount_dir=config.onedrive_dir, config_path=config.rclone_config_file)
        logger.info(f"OneDrive mounted at {config.onedrive_dir}")

    initial_state = await init_state(config=config)

    await run_vesta(config, state=initial_state)


def main() -> None:
    check_dependencies()

    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass
    except Exception:
        logger.exception("Fatal error")


if __name__ == "__main__":
    main()
