"""MCP tools for scheduling reminders"""

from datetime import datetime as dt, timedelta
from typing import Optional, Union
import json
import uuid
from fastmcp import FastMCP
from .scheduler import scheduler, write_notification, DATA_DIR
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

mcp = FastMCP("scheduler-mcp")

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
_scheduler_started = False


def ensure_scheduler_started():
    """Start scheduler if not already started"""
    global _scheduler_started
    if not _scheduler_started:
        try:
            scheduler.start()
            # Sync metadata with actual jobs on startup
            sync_metadata_with_jobs()
            _scheduler_started = True
        except:
            _scheduler_started = True


def sync_metadata_with_jobs():
    """Sync metadata with actual scheduled jobs after startup"""
    global active_reminders
    current_jobs = {job.id for job in scheduler.get_jobs()}

    # Remove metadata for jobs that no longer exist
    to_remove = []
    for reminder_id in active_reminders:
        if reminder_id not in current_jobs:
            to_remove.append(reminder_id)

    for reminder_id in to_remove:
        del active_reminders[reminder_id]

    if to_remove:
        save_metadata(active_reminders)


@mcp.tool
def set_reminder(
    message: str,
    datetime: Optional[str] = None,
    seconds: Union[float, int, str, None] = None,
    minutes: Union[float, int, str, None] = None,
    hours: Union[float, int, str, None] = None,
    days: Union[float, int, str, None] = None,
    recurring: Optional[str] = None,
    interval_minutes: Union[float, int, str, None] = None,
    day_of_week: Optional[str] = None,
    time_of_day: Optional[str] = None,
) -> dict:
    """Set a one-time or recurring reminder

    Args:
        message: The reminder message
        datetime: ISO datetime string or "HH:MM" for daily reminders
        seconds: Seconds from now (for one-time reminders, supports decimals)
        minutes: Minutes from now (for one-time reminders, supports decimals like 0.5)
        hours: Hours from now (for one-time reminders, supports decimals like 1.5)
        days: Days from now (for one-time reminders, supports decimals)
        recurring: "daily", "hourly", "weekly" for recurring reminders
        interval_minutes: Custom interval in minutes for recurring
        day_of_week: For weekly recurring: "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
        time_of_day: For weekly recurring: "HH:MM" format (e.g., "14:30")

    Returns:
        Confirmation with reminder ID and schedule details
    """
    ensure_scheduler_started()

    if not message or not message.strip():
        raise ValueError("Message cannot be empty")

    def parse_number(value, name):
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                raise ValueError(f"Invalid {name} value: '{value}' must be a number")
        return value

    seconds = parse_number(seconds, "seconds")
    minutes = parse_number(minutes, "minutes")
    hours = parse_number(hours, "hours")
    days = parse_number(days, "days")
    interval_minutes = parse_number(interval_minutes, "interval_minutes")

    if not any([datetime, seconds, minutes, hours, days, recurring, interval_minutes]):
        raise ValueError(
            "Must provide either datetime, seconds, minutes, hours, days, recurring, or interval_minutes"
        )

    reminder_id = str(uuid.uuid4())[:8]

    # Determine trigger type
    if recurring == "daily" or (datetime and ":" in datetime and "T" not in datetime):
        hour, minute = datetime.split(":")
        trigger = CronTrigger(hour=int(hour), minute=int(minute))
        schedule_type = "daily"
        next_run = trigger.get_next_fire_time(None, dt.now())
    elif recurring == "hourly":
        trigger = IntervalTrigger(hours=1)
        schedule_type = "hourly"
        next_run = dt.now() + timedelta(hours=1)
    elif recurring == "weekly":
        if day_of_week and time_of_day:
            # Map day names to APScheduler day numbers (0=Monday, 6=Sunday)
            day_map = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }
            if day_of_week.lower() not in day_map:
                raise ValueError(
                    f"Invalid day_of_week: {day_of_week}. Use monday, tuesday, etc."
                )

            if ":" not in time_of_day:
                raise ValueError("time_of_day must be in HH:MM format")

            hour, minute = time_of_day.split(":")
            trigger = CronTrigger(
                day_of_week=day_map[day_of_week.lower()],
                hour=int(hour),
                minute=int(minute),
            )
            schedule_type = f"weekly on {day_of_week} at {time_of_day}"
            next_run = trigger.get_next_fire_time(None, dt.now())
        else:
            trigger = IntervalTrigger(weeks=1)
            schedule_type = "weekly"
            next_run = dt.now() + timedelta(weeks=1)
    elif interval_minutes:
        trigger = IntervalTrigger(minutes=interval_minutes)
        schedule_type = f"every {interval_minutes} minutes"
        next_run = dt.now() + timedelta(minutes=interval_minutes)
    elif seconds or minutes or hours or days:
        delta = timedelta(
            seconds=seconds or 0, minutes=minutes or 0, hours=hours or 0, days=days or 0
        )
        next_run = dt.now() + delta
        trigger = DateTrigger(run_date=next_run)
        parts = []
        if days:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        schedule_type = f"once (in {' '.join(parts)})"
    else:
        next_run = dt.fromisoformat(datetime.replace("Z", "+00:00"))
        trigger = DateTrigger(run_date=next_run)
        schedule_type = "once"

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
    ensure_scheduler_started()
    reminders = []
    for job in scheduler.get_jobs():
        if job.id in active_reminders:
            next_run = job.next_run_time
            reminders.append(
                {
                    "id": job.id,
                    "message": active_reminders[job.id]["message"],
                    "schedule_type": active_reminders[job.id]["schedule_type"],
                    "next_run_time": next_run.isoformat() if next_run else None,
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
    ensure_scheduler_started()
    try:
        scheduler.remove_job(reminder_id)
        if reminder_id in active_reminders:
            message = active_reminders[reminder_id]["message"]
            del active_reminders[reminder_id]
            save_metadata(active_reminders)
            return {
                "reminder_id": reminder_id,
                "message": message,
                "status": "cancelled",
            }
        return {"reminder_id": reminder_id, "status": "cancelled"}
    except:
        return {"reminder_id": reminder_id, "status": "not_found"}
