"""APScheduler setup and notification writing for the unified tasks+reminders daemon."""

import json
import os
import time
from datetime import datetime, UTC
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler() -> BackgroundScheduler:
    # Pin scheduler timezone to UTC so cron triggers fire at the UTC hour/minute
    # extracted from user input in commands.remind_set. Without this, APScheduler
    # defaults to the container's local timezone (tzlocal.get_localzone()), and
    # cron hour/minute set as UTC fire one offset off (e.g. a 07:45 BST schedule
    # fires at 06:45 BST on a London-TZ container).
    return BackgroundScheduler(
        timezone=UTC,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )


_SNOOZE_HINT = "Not actionable right now? Push it back: `tasks remind snooze {rid} --in-hours N`."


def write_notification(notif_dir: Path, type_: str, **fields: object) -> None:
    """Atomically write a `source=tasks` notification JSON file. Single owner of the
    on-disk notification format (source, timestamp, filename pattern, tmp+rename)."""
    notif_dir.mkdir(exist_ok=True)
    notif = {
        "source": "tasks",
        "type": type_,
        **fields,
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }
    filename = f"{int(time.time() * 1e6)}-tasks-{type_}.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    os.replace(tmp, notif_dir / filename)


def write_reminder_notification(
    notif_dir: Path,
    reminder_id: str,
    message: str,
    *,
    task_id: str | None = None,
    extra: dict | None = None,
    snooze_hint: bool = False,
):
    """Write a reminder notification JSON file. `snooze_hint` appends the snooze tip; set it for
    one-shot user reminders only (recurring ones fire again anyway, auto ones carry their own menu)."""
    if not reminder_id or not message:
        raise ValueError("reminder_id and message required")

    full_message = f"{message}\n{_SNOOZE_HINT.format(rid=reminder_id)}" if snooze_hint else message
    write_notification(notif_dir, "reminder", message=full_message, reminder_id=reminder_id, task_id=task_id, **(extra or {}))
