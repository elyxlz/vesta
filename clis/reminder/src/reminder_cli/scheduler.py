import json
import time
from datetime import datetime, UTC
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler


def create_scheduler(data_dir: Path) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        job_defaults={
            "coalesce": True,
            "max_instances": 1,
        },
    )
    return scheduler


def write_notification(notif_dir: Path, reminder_id: str, message: str, *, data: dict | None = None):
    if not reminder_id or not message:
        raise ValueError("reminder_id and message required")

    notif_dir.mkdir(exist_ok=True)

    notif = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "scheduler",
        "type": "reminder",
        "message": message,
        "reminder_id": reminder_id,
        "agent_only": True,
        **(data or {}),
    }

    filename = f"{int(time.time() * 1e6)}-scheduler-reminder.json"
    (notif_dir / filename).write_text(json.dumps(notif, indent=2))
