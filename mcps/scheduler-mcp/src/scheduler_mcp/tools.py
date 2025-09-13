"""MCP tools for scheduling reminders"""

from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
import json
from fastmcp import FastMCP
from .scheduler import scheduler, write_notification
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import uuid

mcp = FastMCP("scheduler-mcp")

DATA_DIR = Path("data") / "scheduler"
DATA_DIR.mkdir(parents=True, exist_ok=True)
METADATA_FILE = DATA_DIR / "reminders_metadata.json"


def load_metadata():
    """Load reminder metadata from file"""
    if METADATA_FILE.exists():
        return json.loads(METADATA_FILE.read_text())
    return {}


def save_metadata(data):
    """Save reminder metadata to file"""
    METADATA_FILE.write_text(json.dumps(data, indent=2))


active_reminders = load_metadata()


@mcp.tool
def set_reminder(
    message: str,
    time_str: Optional[str] = None,
    minutes: Optional[int] = None,
    recurring: Optional[str] = None,
    interval_minutes: Optional[int] = None,
) -> dict:
    """Set a one-time or recurring reminder

    Args:
        message: The reminder message
        time_str: Time string - ISO format or "HH:MM" for daily
        minutes: Minutes from now (for one-time reminders)
        recurring: "daily", "hourly", "weekly" for recurring reminders
        interval_minutes: Custom interval in minutes for recurring

    Returns:
        Confirmation with reminder ID and schedule details
    """
    if not any([time_str, minutes]):
        raise ValueError("Must provide either time_str or minutes")

    reminder_id = str(uuid.uuid4())[:8]

    # Determine trigger type
    if recurring == "daily" or (time_str and ":" in time_str and "T" not in time_str):
        # Daily reminder at specific time
        hour, minute = time_str.split(":")
        trigger = CronTrigger(hour=int(hour), minute=int(minute))
        schedule_type = "daily"
        next_run = trigger.get_next_fire_time(None, datetime.now())
    elif recurring == "hourly":
        trigger = IntervalTrigger(hours=1)
        schedule_type = "hourly"
        next_run = datetime.now() + timedelta(hours=1)
    elif recurring == "weekly":
        trigger = IntervalTrigger(weeks=1)
        schedule_type = "weekly"
        next_run = datetime.now() + timedelta(weeks=1)
    elif interval_minutes:
        trigger = IntervalTrigger(minutes=interval_minutes)
        schedule_type = f"every {interval_minutes} minutes"
        next_run = datetime.now() + timedelta(minutes=interval_minutes)
    elif minutes:
        # One-time reminder in X minutes
        next_run = datetime.now() + timedelta(minutes=minutes)
        trigger = DateTrigger(run_date=next_run)
        schedule_type = "once"
    else:
        # One-time reminder at specific datetime
        next_run = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        trigger = DateTrigger(run_date=next_run)
        schedule_type = "once"

    # Schedule the job
    scheduler.add_job(
        write_notification, trigger, args=[reminder_id, message], id=reminder_id
    )

    active_reminders[reminder_id] = {
        "message": message,
        "schedule_type": schedule_type,
        "next_run": next_run.isoformat() if next_run else "calculating...",
    }
    save_metadata(active_reminders)

    return {
        "reminder_id": reminder_id,
        "message": message,
        "schedule_type": schedule_type,
        "next_run": active_reminders[reminder_id]["next_run"],
        "status": "scheduled",
    }


@mcp.tool
def list_reminders() -> list[dict]:
    """List all active reminders"""
    reminders = []
    for job in scheduler.get_jobs():
        if job.id in active_reminders:
            next_run = job.next_run_time
            reminders.append(
                {
                    "reminder_id": job.id,
                    "message": active_reminders[job.id]["message"],
                    "schedule_type": active_reminders[job.id]["schedule_type"],
                    "next_run": next_run.isoformat() if next_run else None,
                    "status": "active",
                }
            )
    return reminders


@mcp.tool
def cancel_reminder(reminder_id: str) -> dict:
    """Cancel a scheduled reminder

    Args:
        reminder_id: ID of the reminder to cancel

    Returns:
        Confirmation of cancellation
    """
    scheduler.remove_job(reminder_id)

    if reminder_id in active_reminders:
        message = active_reminders[reminder_id]["message"]
        del active_reminders[reminder_id]
        return {"reminder_id": reminder_id, "message": message, "status": "cancelled"}

    return {"reminder_id": reminder_id, "status": "not_found"}
