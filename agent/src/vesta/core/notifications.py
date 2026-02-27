import asyncio
import datetime as dt
import json
import pathlib as pl

import pydantic

import vesta.core.effects as vfx
import vesta.models as vm
from vesta import logger
from vesta.core.init import load_prompt


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


async def delete_notification_files(notifications: list[vm.Notification]) -> None:
    paths = {n.file_path for n in notifications if n.file_path}
    for path_str in paths:
        pl.Path(path_str).unlink(missing_ok=True)


def format_notification_batch(notifications: list[vm.Notification], *, suffix: str = "") -> str:
    suffix_str = f"\n\n{suffix}" if suffix else ""
    if len(notifications) == 1:
        return notifications[0].format_for_display() + suffix_str

    prompts = [n.format_for_display() for n in notifications]
    return "[NOTIFICATIONS]\n" + "\n".join(prompts) + suffix_str


def should_flush_buffer(
    buffer: list[vm.Notification], *, buffer_start_time: dt.datetime | None, current_time: dt.datetime, buffer_delay: int
) -> bool:
    if not buffer or not buffer_start_time:
        return False
    return (current_time - buffer_start_time).total_seconds() >= buffer_delay


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


async def process_batch(
    notifications: list[vm.Notification], *, queue: asyncio.Queue, state: vm.State, config: vm.VestaConfig
) -> None:
    if not notifications:
        return

    from vesta.core.client import attempt_interrupt

    suffix = load_prompt("notification_suffix", config) or ""
    prompt = format_notification_batch(notifications, suffix=suffix)

    if state.client:
        await attempt_interrupt(state, config=config, reason="Notification interrupt")

    await queue.put((prompt, True))
    await delete_notification_files(notifications)


async def queue_greeting(queue: asyncio.Queue, *, config: vm.VestaConfig, first_start: bool) -> None:
    name = "first_start" if first_start else "returning_start"
    prompt = load_prompt(name, config)
    if not prompt or not prompt.strip():
        return

    await queue.put((prompt.strip(), False))
    logger.startup(f"Queued {'first start' if first_start else 'returning'} greeting")
