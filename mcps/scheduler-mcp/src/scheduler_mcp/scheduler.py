import json
import time
import os
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

NOTIF_DIR = Path(os.environ.get("NOTIFICATIONS_DIR", "../../notifications")).resolve()
DATA_DIR = Path(os.environ.get("DATA_DIR", "data")) / "scheduler"
DATA_DIR.mkdir(parents=True, exist_ok=True)

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{DATA_DIR}/reminders.db")},
    job_defaults={
        "coalesce": True,
        "max_instances": 1,
        "misfire_grace_time": 86400 * 7,
    },
)


def write_notification(reminder_id: str, message: str, data: dict = None):
    if not reminder_id or not message:
        raise ValueError("reminder_id and message required")

    NOTIF_DIR.mkdir(exist_ok=True)

    metadata = {"reminder_id": reminder_id}
    if data:
        metadata.update(data)

    notif = {
        "timestamp": datetime.now().isoformat(),
        "source": "scheduler",
        "type": "reminder",
        "message": message,
        "metadata": metadata,
    }

    filename = f"{int(time.time() * 1e6)}-scheduler-reminder.json"
    (NOTIF_DIR / filename).write_text(json.dumps(notif, indent=2))
