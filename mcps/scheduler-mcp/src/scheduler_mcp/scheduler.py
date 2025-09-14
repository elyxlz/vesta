"""Simple scheduler that writes notifications at specified times"""

import json
import time
import os
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

# Get directories from environment or fail
NOTIF_DIR = Path(os.environ.get('NOTIFICATIONS_DIR', '../../notifications')).resolve()
DATA_DIR = Path(os.environ.get('DATA_DIR', 'data')) / "scheduler"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Configure scheduler with persistent storage
scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{DATA_DIR}/reminders.db")},
    job_defaults={'coalesce': True, 'max_instances': 1, 'misfire_grace_time': 60}
)

def write_notification(reminder_id: str, message: str, data: dict = None):
    """Write notification when reminder triggers"""
    if not reminder_id:
        raise ValueError("reminder_id cannot be empty")
    if not message:
        raise ValueError("message cannot be empty")
    
    NOTIF_DIR.mkdir(exist_ok=True)
    
    notif = {
        "timestamp": datetime.now().isoformat(),
        "source": "scheduler",
        "type": "reminder",
        "data": {
            "reminder_id": reminder_id, 
            "message": message,
            **(data if data else {})
        },
    }
    
    assert "timestamp" in notif, "Missing timestamp field"
    assert "source" in notif, "Missing source field"
    assert "data" in notif, "Missing data field"
    assert "message" in notif["data"], "Missing message in data field"
    
    filename = f"{int(time.time() * 1e6)}-scheduler-reminder.json"
    (NOTIF_DIR / filename).write_text(json.dumps(notif, indent=2))