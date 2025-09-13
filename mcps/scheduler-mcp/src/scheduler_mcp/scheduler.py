"""Simple scheduler that writes notifications at specified times"""

import json
import time
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

NOTIF_DIR = Path("notifications")
DATA_DIR = Path("data") / "scheduler"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "reminders.db"

# Configure scheduler with persistent storage
jobstores = {"default": SQLAlchemyJobStore(url=f"sqlite:///{DB_PATH}")}

scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler.start()


def write_notification(reminder_id: str, message: str, data: dict = None):
    """Write notification when reminder triggers"""
    NOTIF_DIR.mkdir(exist_ok=True)

    notif = {
        "timestamp": datetime.now().isoformat(),
        "source": "scheduler",
        "type": "reminder",
        "data": {"reminder_id": reminder_id, "message": message, **(data or {})},
    }

    filename = f"{int(time.time() * 1e6)}-scheduler-reminder.json"
    (NOTIF_DIR / filename).write_text(json.dumps(notif, indent=2))
