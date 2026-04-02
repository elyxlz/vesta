"""APScheduler setup and notification writing for the unified tasks+reminders daemon."""

import json
import os
import time
from datetime import datetime, UTC
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(
        job_defaults={"coalesce": True, "max_instances": 1},
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

    notif = {
        "source": "tasks",
        "type": "reminder",
        "message": message,
        "reminder_id": reminder_id,
        "task_id": task_id,
        **(extra or {}),
        "timestamp": datetime.now(UTC).isoformat(),
    }

    filename = f"{int(time.time() * 1e6)}-tasks-reminder.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    os.replace(tmp, notif_dir / filename)


def write_task_due_notification(
    notif_dir: Path,
    task_id: str,
    title: str,
    due_date: str,
    reminder_window: str,
    priority: int,
):
    """Write a task-due notification JSON file."""
    notif_dir.mkdir(exist_ok=True)

    priority_labels = {1: "low", 2: "normal", 3: "high"}
    notif = {
        "source": "tasks",
        "type": "task_due",
        "title": title,
        "due_date": due_date,
        "priority": priority_labels.get(priority, "normal"),
        "reminder_window": reminder_window,
        "task_id": task_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    filename = f"{int(time.time() * 1e6)}-tasks-due.json"
    tmp = notif_dir / f"{filename}.tmp"
    tmp.write_text(json.dumps(notif, indent=2))
    os.replace(tmp, notif_dir / filename)
