import asyncio
import datetime as dt

import vesta.core.effects as vfx
import vesta.models as vm
import vesta.utils as vu
from vesta import logger


async def load_notifications(*, config: vm.VestaConfig) -> list[vm.Notification]:
    file_contents = vfx.load_notification_files(config.notifications_dir)

    notifications = []
    for file, content in file_contents:
        try:
            data = vu.parse_notification_file_content(content)
            notif = vm.Notification(**data)
            notif.file_path = str(file)
            notifications.append(notif)
        except Exception as e:
            logger.error(f"Failed to parse notification {file.name}: {e}")

    return notifications


async def maybe_enqueue_whatsapp_greeting(queue: asyncio.Queue, *, config: vm.VestaConfig) -> None:
    if "whatsapp" not in config.mcps:
        return

    prompt = (config.whatsapp_greeting_prompt or "").strip()
    if not prompt:
        return

    await queue.put((prompt, False))
    logger.mcp("Queued WhatsApp greeting task")


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    paths = vu.extract_paths_to_delete(notifications)
    vfx.delete_files(paths)


async def load_and_display_new_notifications(
    notification_buffer: list[vm.Notification], *, buffer_start_time: dt.datetime | None, config: vm.VestaConfig
) -> tuple[list[vm.Notification], dt.datetime | None]:
    new_notifs = await load_notifications(config=config)

    if new_notifs:
        existing_paths = {n.file_path for n in notification_buffer if n.file_path}
        truly_new = vu.filter_new_notifications(new_notifs, existing_paths=existing_paths)

        if truly_new:
            notification_buffer.extend(truly_new)
            now = vfx.get_current_time()
            if buffer_start_time is None:
                buffer_start_time = now

            for notif in truly_new:
                logger.notification(notif.model_dump_json(indent=2))

    return notification_buffer, buffer_start_time
