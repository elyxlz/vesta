"""Background processing loops."""

import asyncio

import vesta.models as vm
import vesta.utils as vu
import vesta.core.effects as vfx
from vesta import logger
from vesta.config import Messages
from vesta.core.client import process_message, attempt_interrupt, reset_client_context
from vesta.core.dreamer import preserve_memory
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
        logger.info(f"Interrupting task for {len(notifications)} notifications")
        success = await attempt_interrupt(state, config=config, reason="Notification interrupt")
        if not success:
            logger.warning("Could not interrupt current task; queued notification for later")
    if decision in {"queue", "interrupt"}:
        await queue.put((prompt, True))

    await delete_notification_files(notifications)


async def message_processor(queue: asyncio.Queue, *, state: vm.State, config: vm.VestaConfig) -> None:
    while state.shutdown_event and not state.shutdown_event.is_set():
        try:
            msg, is_user = await asyncio.wait_for(queue.get(), timeout=1.0)
        except TimeoutError:
            continue

        logger.debug(f"Processing message (is_user={is_user}, length={len(msg)})")

        async with state.processing_lock:
            state.is_processing = True

        try:
            responses, _ = await process_message(msg, state=state, config=config, is_user=is_user)

            for response in responses:
                if response and response.strip():
                    logger.info(f"ASSISTANT: {response}")
        finally:
            async with state.processing_lock:
                state.is_processing = False


async def check_proactive_task(queue: asyncio.Queue, *, config: vm.VestaConfig) -> None:
    logger.info(Messages.PROACTIVE_CHECK)
    await queue.put((config.proactive_check_message, False))


async def process_nightly_memory(state: vm.State, *, config: vm.VestaConfig) -> None:
    now = vfx.get_current_time()
    if config.nightly_memory_hour is not None and now.hour == config.nightly_memory_hour:
        if state.last_memory_consolidation is None or now.date() > state.last_memory_consolidation.date():
            logger.info(Messages.NIGHTLY_DREAMER)
            updated = await preserve_memory(state, config=config)
            state.last_memory_consolidation = now
            logger.info("[DREAMER] Nightly consolidation complete")
            if updated:
                await reset_client_context(state, config=config)
            if config.nightly_memory_completion_message:
                state.pending_system_message = config.nightly_memory_completion_message


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

            await process_nightly_memory(state, config=config)

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
