"""Background processing loops."""

import asyncio

from claude_agent_sdk import ClaudeSDKClient

import vesta.models as vm
import vesta.utils as vu
import vesta.core.effects as vfx
from vesta import logger
from vesta.core.client import process_message, attempt_interrupt, build_client_options
from vesta.core.dreamer import build_memory_consolidation_prompt
from vesta.core.notifications import load_and_display_new_notifications, delete_notification_files


async def process_notification_batch(
    notifications: list[vm.Notification], *, queue: asyncio.Queue, state: vm.State, config: vm.VestaConfig
) -> None:
    if not notifications:
        return

    async with state.processing_lock:
        is_processing = state.is_processing
        has_client = state.client is not None
    decision = vu.decide_notification_action(notifications, is_processing=is_processing, has_client=has_client)
    prompt = vu.format_notification_batch(notifications, suffix=config.notification_suffix)

    if decision == "interrupt" and state.client:
        logger.notification(f"Interrupting task for {len(notifications)} notifications")
        success = await attempt_interrupt(state, config=config, reason="Notification interrupt")
        if not success:
            logger.warning("Could not interrupt current task; queued notification for later")
    if decision in {"queue", "interrupt"}:
        await queue.put((prompt, True))

    await delete_notification_files(notifications)


async def _process_message_safely(msg: str, *, is_user: bool, state: vm.State, config: vm.VestaConfig) -> bool:
    """Process a single message with error handling. Returns False if session should reset."""
    logger.debug(f"Processing message (is_user={is_user}, length={len(msg)})")

    async with state.processing_lock:
        state.is_processing = True
    try:
        responses, _ = await process_message(msg, state=state, config=config, is_user=is_user)
        for response in responses:
            if response and response.strip():
                logger.assistant(response)
        return True
    except (OSError, RuntimeError, ValueError, TimeoutError) as e:
        logger.error(f"Error processing message: {e}")
        state.pending_error_context = f"[System: Previous request failed with error: {e}. Session was reset.]"
        state.reset_requested = True
        return False
    finally:
        async with state.processing_lock:
            state.is_processing = False


async def message_processor(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    """Process messages in a loop, managing client lifecycle with async with."""
    while state.shutdown_event and not state.shutdown_event.is_set():
        logger.client("Creating new client session...")
        options = build_client_options(config, state)
        async with ClaudeSDKClient(options=options) as client:
            state.client = client
            logger.client("Client session started")
            if state.pending_error_context:
                await queue.put((state.pending_error_context, False))
                state.pending_error_context = None

            while not state.shutdown_event.is_set() and not state.reset_requested:
                try:
                    msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    continue

                if not await _process_message_safely(msg, is_user=is_user, state=state, config=config):
                    break

            if state.reset_requested:
                logger.client("Reset requested, closing client session...")
                state.reset_requested = False
                state.sub_agent_context = None
                state.session_id = None

        state.client = None
        logger.client("Client session closed")


async def check_proactive_task(queue: asyncio.Queue, *, config: vm.VestaConfig) -> None:
    logger.proactive("Running 60-minute check...")
    await queue.put((config.proactive_check_message, False))


async def process_nightly_memory(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    if config.ephemeral:
        return

    now = vfx.get_current_time()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_memory_consolidation is None or now.date() > state.last_memory_consolidation.date():
            logger.dreamer("Nightly memory consolidation...")
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
