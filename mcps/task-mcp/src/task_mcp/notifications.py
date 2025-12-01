import json
import time
from datetime import datetime, timezone
from pathlib import Path


def write_notification(
    notif_dir: Path,
    task_id: str,
    title: str,
    due_date: str,
    reminder_window: str,
    priority: int,
):
    notif_dir.mkdir(exist_ok=True)

    priority_label = {1: "low", 2: "normal", 3: "high"}.get(priority, "normal")

    notif = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "task",
        "type": "task_due",
        "message": f"Task due in {reminder_window}: {title} ({priority_label} priority)",
        "metadata": {
            "task_id": task_id,
            "title": title,
            "due_date": due_date,
            "priority": priority,
            "reminder_window": reminder_window,
        },
    }

    filename = f"{int(time.time() * 1e6)}-task-due.json"
    (notif_dir / filename).write_text(json.dumps(notif, indent=2))
