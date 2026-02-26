import json
import time
from datetime import datetime, UTC
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

    PRIORITY_LABELS = {1: "low", 2: "normal", 3: "high"}
    if priority not in PRIORITY_LABELS:
        raise ValueError(f"Invalid priority {priority}, must be 1, 2, or 3")

    notif = {
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "todo",
        "type": "todo_due",
        "task_id": task_id,
        "title": title,
        "due_date": due_date,
        "priority": PRIORITY_LABELS[priority],
        "reminder_window": reminder_window,
    }

    filename = f"{int(time.time() * 1e6)}-todo-due.json"
    (notif_dir / filename).write_text(json.dumps(notif, indent=2))
