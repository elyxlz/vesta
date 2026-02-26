"""Background processing loops."""

import asyncio
import pathlib as pl
import shutil

from claude_agent_sdk import ClaudeSDKClient, ClaudeSDKError

import vesta.models as vm
import vesta.utils as vu
import vesta.core.effects as vfx
from vesta import logger
from vesta.core.client import process_message, attempt_interrupt, build_client_options
from vesta.core.dreamer import build_memory_consolidation_prompt
from vesta.core.init import load_prompt
from vesta.core.notifications import load_and_display_new_notifications, delete_notification_files


async def process_notification_batch(
    notifications: list[vm.Notification], *, queue: asyncio.Queue, state: vm.State, config: vm.VestaConfig
) -> None:
    if not notifications:
        return

    suffix = load_prompt("notification_suffix", config) or ""
    prompt = vu.format_notification_batch(notifications, suffix=suffix)

    if state.client:
        await attempt_interrupt(state, config=config, reason="Notification interrupt")

    await queue.put((prompt, True))
    await delete_notification_files(notifications)


async def _process_message_safely(msg: str, *, is_user: bool, state: vm.State, config: vm.VestaConfig) -> bool:
    """Process a single message with error handling. Returns False if session should reset."""
    try:
        responses, _ = await process_message(msg, state=state, config=config, is_user=is_user)
        for response in responses:
            if response and response.strip():
                logger.assistant(response)
        return True
    except (ClaudeSDKError, OSError, RuntimeError, ValueError, TimeoutError) as e:
        logger.error(f"Error processing message: {e}")
        state.pending_context = f"[System: Previous request failed with error: {e}. Session was reset.]"
        state.session_id = None
        return False


async def message_processor(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    """Process messages in a loop, managing client lifecycle with async with."""
    while state.shutdown_event and not state.shutdown_event.is_set():
        logger.client("Creating new client session...")
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            logger.client("Client session started")

            if state.pending_context:
                await queue.put((state.pending_context, False))
                state.pending_context = None

            while not state.shutdown_event.is_set() and state.pending_context is None:
                try:
                    msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                if not await _process_message_safely(msg, is_user=is_user, state=state, config=config):
                    break

        state.client = None
        logger.client("Client session closed")


async def check_proactive_task(queue: asyncio.Queue, *, config: vm.VestaConfig) -> None:
    prompt = load_prompt("proactive_check", config)
    if not prompt:
        return
    logger.proactive("Running 60-minute check...")
    await queue.put((prompt, False))


def _session_jsonl_path(state: vm.State, config: vm.VestaConfig) -> pl.Path | None:
    if not state.session_id:
        return None
    slug = str(config.state_dir).replace("/", "-")
    path = pl.Path.home() / ".claude" / "projects" / slug / f"{state.session_id}.jsonl"
    if path.exists():
        return path
    return None


def archive_conversation(state: vm.State, config: vm.VestaConfig) -> None:
    src = _session_jsonl_path(state, config)
    if not src:
        logger.dreamer("No session transcript to archive")
        return

    config.conversations_dir.mkdir(parents=True, exist_ok=True)
    now = vfx.get_current_time()
    dest = config.conversations_dir / f"{now.strftime('%Y-%m-%d_%H%M%S')}.jsonl"
    shutil.copy2(src, dest)
    logger.dreamer(f"Archived conversation to {dest}")


async def process_nightly_memory(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    if config.ephemeral:
        return

    now = vfx.get_current_time()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_memory_consolidation is None or now.date() > state.last_memory_consolidation.date():
            logger.dreamer("Nightly memory consolidation...")
            archive_conversation(state, config)
            prompt = build_memory_consolidation_prompt(config)
            await queue.put((prompt, False))
            state.last_memory_consolidation = now
            logger.dreamer("Memory consolidation prompt queued")


async def monitor_loop(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    last_proactive = vfx.get_current_time()
    notification_buffer: list[vm.Notification] = []
    buffer_start_time = None

    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            await asyncio.sleep(config.notification_check_interval)

            if state.shutdown_event and state.shutdown_event.is_set():
                break

            now = vfx.get_current_time()

            if (now - last_proactive).total_seconds() >= config.proactive_check_interval * 60:
                await check_proactive_task(queue, config=config)
                last_proactive = now

            await process_nightly_memory(queue, state=state, config=config)

            notification_buffer, buffer_start_time = await load_and_display_new_notifications(
                notification_buffer, buffer_start_time=buffer_start_time, config=config
            )

            if vu.should_process_notification_buffer(
                notification_buffer, buffer_start_time=buffer_start_time, current_time=now, buffer_delay=config.notification_buffer_delay
            ):
                await process_notification_batch(notification_buffer, queue=queue, state=state, config=config)
                notification_buffer = []
                buffer_start_time = None
        except asyncio.CancelledError:
            break
