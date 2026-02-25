import asyncio
import datetime as dt
import json
import pathlib as pl

import pydantic

import vesta.core.effects as vfx
import vesta.models as vm
from vesta import logger


def _load_notification_files(directory: pl.Path) -> list[tuple[pl.Path, str]]:
    if not directory.exists():
        return []
    return [(f, f.read_text(encoding="utf-8")) for f in directory.glob("*.json")]


async def load_notifications(*, config: vm.VestaConfig) -> list[vm.Notification]:
    file_contents = _load_notification_files(config.notifications_dir)

    notifications = []
    for file, content in file_contents:
        try:
            data = json.loads(content)
            notif = vm.Notification(**data)
            notif.file_path = str(file)
            notifications.append(notif)
        except (json.JSONDecodeError, pydantic.ValidationError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse notification {file.name}: {e}")

    return notifications


async def maybe_enqueue_whatsapp_greeting(queue: asyncio.Queue, *, config: vm.VestaConfig) -> None:
    prompt = (config.whatsapp_greeting_prompt or "").strip()
    if not prompt:
        return

    await queue.put((prompt, False))
    logger.startup("Queued WhatsApp greeting task")


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    paths = {n.file_path for n in notifications if n.file_path}
    for path_str in paths:
        pl.Path(path_str).unlink(missing_ok=True)


async def load_and_display_new_notifications(
    notification_buffer: list[vm.Notification], *, buffer_start_time: dt.datetime | None, config: vm.VestaConfig
) -> tuple[list[vm.Notification], dt.datetime | None]:
    new_notifs = await load_notifications(config=config)

    if new_notifs:
        existing_paths = {n.file_path for n in notification_buffer if n.file_path}
        truly_new = [n for n in new_notifs if n.file_path not in existing_paths]

        if truly_new:
            notification_buffer.extend(truly_new)
            now = vfx.get_current_time()
            if buffer_start_time is None:
                buffer_start_time = now

            for notif in truly_new:
                logger.notification(notif.model_dump_json(indent=2))

    return notification_buffer, buffer_start_time
