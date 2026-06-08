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


_REARM_HINT = (
    "Tip: if no action is taken on this reminder, rearm it for a later date"
    " via `tasks remind delete {rid}` followed by a new `tasks remind ... --at ...`."
)


def write_reminder_notification(
    notif_dir: Path,
    reminder_id: str,
    message: str,
    *,
    task_id: str | None = None,
    extra: dict | None = None,
):
    """Write a reminder notification JSON file."""
    if not reminder_id or not message:
        raise ValueError("reminder_id and message required")

    notif_dir.mkdir(exist_ok=True)

    full_message = f"{message}\n{_REARM_HINT.format(rid=reminder_id)}"

    notif = {
        "source": "tasks",
        "type": "reminder",
        "message": full_message,
        "reminder_id": reminder_id,
        "task_id": task_id,
        **(extra or {}),
        "timestamp": datetime.now(UTC).replace(microsecond=0).isoformat(),
    }

    filename = f"{int(time.time() * 1e6)}-tasks-reminder.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    os.replace(tmp, notif_dir / filename)
