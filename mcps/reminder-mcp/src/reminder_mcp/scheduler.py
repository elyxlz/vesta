import json
import time
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore


def create_scheduler(data_dir: Path) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{data_dir}/reminders.db")},
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

    metadata = {"reminder_id": reminder_id, **(data or {})}

    notif = {
        "timestamp": datetime.now().isoformat(),
        "source": "scheduler",
        "type": "reminder",
        "message": message,
        "metadata": metadata,
    }

    filename = f"{int(time.time() * 1e6)}-scheduler-reminder.json"
    (notif_dir / filename).write_text(json.dumps(notif, indent=2))
