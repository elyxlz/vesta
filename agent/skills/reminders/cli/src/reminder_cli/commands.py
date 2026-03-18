from datetime import datetime, timedelta, UTC
from contextlib import closing
from pathlib import Path
from typing import TypedDict
import json
import logging
import uuid

from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError

from .config import Config
from . import db
from .scheduler import write_notification

logger = logging.getLogger(__name__)


class TriggerData(TypedDict, total=False):
    type: str
    run_date: str
    month: int
    day: int
    day_of_week: str
    hour: int
    minute: int
    hours: int


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _parse_datetime(s: str) -> datetime:
    parsed = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _to_utc(datetime_str: str, timezone_str: str) -> datetime:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        local_tz = ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: '{timezone_str}'. Use IANA names like 'Europe/London' or 'America/New_York'.")

    naive = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
    if naive.tzinfo is not None:
        return naive.astimezone(UTC)
    return naive.replace(tzinfo=local_tz).astimezone(UTC)


def send_reminder_job(reminder_id: str, *, message: str, data_dir, notif_dir):
    data_dir = Path(data_dir)
    notif_dir = Path(notif_dir)

    msg_preview = message[:50] + "..." if len(message) > 50 else message
    logger.info(f"Firing reminder {reminder_id}: {msg_preview}")
    write_notification(notif_dir, reminder_id, message)

    with closing(db.get_db(data_dir)) as conn:
        cursor = conn.execute("SELECT trigger_data FROM reminders WHERE id = ?", (reminder_id,))
        row = cursor.fetchone()
        if row and row["trigger_data"]:
            trigger_data = json.loads(row["trigger_data"])
            if trigger_data["type"] == "date":
                conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                conn.commit()


def restore_all_jobs(config: Config, scheduler: BackgroundScheduler, *, notif_dir: Path | None = None):
    now = _now_utc()
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT id, message, trigger_data FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL")

        for row in cursor:
            reminder_id = row["id"]
            try:
                trigger_data: TriggerData = json.loads(row["trigger_data"])
                trigger_type = trigger_data["type"] if "type" in trigger_data else None

                if trigger_type == "date":
                    run_date_str = trigger_data["run_date"] if "run_date" in trigger_data else None
                    if not run_date_str:
                        logger.warning(f"Reminder {reminder_id}: date trigger missing 'run_date', skipping")
                        continue
                    run_date = _parse_datetime(run_date_str)
                    if run_date < now:
                        logger.info(f"Reminder {reminder_id}: past due, sending missed notification")
                        if notif_dir:
                            write_notification(notif_dir, reminder_id, row["message"], data={"missed": True})
                        conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                        continue
                    trigger = DateTrigger(run_date=run_date)

                elif trigger_type == "cron":
                    trigger = CronTrigger(
                        month=trigger_data["month"] if "month" in trigger_data else None,
                        day=trigger_data["day"] if "day" in trigger_data else None,
                        day_of_week=trigger_data["day_of_week"] if "day_of_week" in trigger_data else None,
                        hour=trigger_data["hour"] if "hour" in trigger_data else None,
                        minute=trigger_data["minute"] if "minute" in trigger_data else None,
                    )

                elif trigger_type == "interval":
                    if "hours" not in trigger_data:
                        logger.warning(f"Reminder {reminder_id}: interval trigger missing 'hours', using default 1")
                    trigger = IntervalTrigger(hours=trigger_data["hours"] if "hours" in trigger_data else 1)

                else:
                    logger.warning(f"Reminder {reminder_id}: unknown trigger type '{trigger_type}', skipping")
                    continue

                scheduler.add_job(
                    func=send_reminder_job,
                    trigger=trigger,
                    args=[reminder_id],
                    kwargs={"message": row["message"], "data_dir": config.data_dir, "notif_dir": str(notif_dir) if notif_dir else ""},
                    id=reminder_id,
                    replace_existing=True,
                )
                logger.info(f"Restored reminder {reminder_id} ({trigger_type})")

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Failed to restore reminder {reminder_id}: {e}")

        conn.commit()


def set_reminder(
    config: Config,
    scheduler: BackgroundScheduler,
    *,
    message: str,
    scheduled_datetime: str | None = None,
    tz: str | None = None,
    in_minutes: int | None = None,
    in_hours: int | None = None,
    in_days: int | None = None,
    recurring: str | None = None,
    notif_dir: Path | None = None,
) -> dict:
    reminder_id = str(uuid.uuid4())[:8]
    trigger_data = None

    if recurring == "hourly":
        trigger = IntervalTrigger(hours=1)
        schedule_info = "hourly"
        trigger_data = {"type": "interval", "hours": 1}
    elif recurring in ("daily", "weekly", "monthly", "yearly"):
        if not scheduled_datetime or not tz:
            raise ValueError(f"scheduled_datetime and tz are required for {recurring} reminders")
        utc_dt = _to_utc(scheduled_datetime, tz)
        h, m = utc_dt.hour, utc_dt.minute

        if recurring == "daily":
            trigger = CronTrigger(hour=h, minute=m)
            schedule_info = f"daily at {h:02d}:{m:02d} UTC"
            trigger_data = {"type": "cron", "hour": h, "minute": m}
        elif recurring == "weekly":
            day_name = utc_dt.strftime("%a").lower()
            trigger = CronTrigger(day_of_week=day_name, hour=h, minute=m)
            schedule_info = f"weekly on {day_name} at {h:02d}:{m:02d} UTC"
            trigger_data = {"type": "cron", "day_of_week": day_name, "hour": h, "minute": m}
        elif recurring == "monthly":
            trigger = CronTrigger(day=utc_dt.day, hour=h, minute=m)
            schedule_info = f"monthly on day {utc_dt.day} at {h:02d}:{m:02d} UTC"
            trigger_data = {"type": "cron", "day": utc_dt.day, "hour": h, "minute": m}
        else:
            trigger = CronTrigger(month=utc_dt.month, day=utc_dt.day, hour=h, minute=m)
            schedule_info = f"yearly on {utc_dt.month}/{utc_dt.day} at {h:02d}:{m:02d} UTC"
            trigger_data = {"type": "cron", "month": utc_dt.month, "day": utc_dt.day, "hour": h, "minute": m}
    elif scheduled_datetime:
        if not tz:
            raise ValueError("tz is required when scheduled_datetime is provided")
        utc_dt = _to_utc(scheduled_datetime, tz)
        trigger = DateTrigger(run_date=utc_dt)
        schedule_info = f"once at {utc_dt.isoformat()}"
        trigger_data = {"type": "date", "run_date": utc_dt.isoformat()}
    else:
        for name, val in [("in_minutes", in_minutes), ("in_hours", in_hours), ("in_days", in_days)]:
            if val is not None and val <= 0:
                raise ValueError(f"{name} must be positive")
        offset = timedelta(minutes=in_minutes or 0, hours=in_hours or 0, days=in_days or 0)
        if not offset.total_seconds():
            raise ValueError("Must specify when to send reminder")
        run_time = _now_utc() + offset
        trigger = DateTrigger(run_date=run_time)
        parts = [f"{v} {u}" for v, u in [(in_days, "days"), (in_hours, "hours"), (in_minutes, "minutes")] if v]
        schedule_info = f"once (in {' '.join(parts)})"
        trigger_data = {"type": "date", "run_date": run_time.isoformat()}

    scheduler.add_job(
        func=send_reminder_job,
        trigger=trigger,
        args=[reminder_id],
        kwargs={"message": message, "data_dir": config.data_dir, "notif_dir": str(notif_dir) if notif_dir else ""},
        id=reminder_id,
        replace_existing=True,
    )

    job = scheduler.get_job(reminder_id)
    next_run = job.next_run_time if job else None

    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reminders (id, message, schedule_type, scheduled_time, completed, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
            (
                reminder_id,
                message,
                schedule_info,
                next_run.isoformat() if next_run else None,
                json.dumps(trigger_data) if trigger_data else None,
            ),
        )
        conn.commit()
        cursor = conn.execute("SELECT created_at FROM reminders WHERE id = ?", (reminder_id,))
        created_at = cursor.fetchone()["created_at"]

    return {
        "id": reminder_id,
        "message": message,
        "schedule": schedule_info,
        "next_run": next_run.isoformat() if next_run else None,
        "created_at": created_at,
        "status": "scheduled",
    }


def list_reminders(config: Config, scheduler: BackgroundScheduler, *, limit: int = 50) -> list[dict]:
    jobs = {job.id: job for job in scheduler.get_jobs()}
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE completed = 0 ORDER BY created_at DESC LIMIT ?", (limit,))
        reminders = []
        for row in cursor:
            job = jobs[row["id"]] if row["id"] in jobs else None
            reminders.append(
                {
                    "id": row["id"],
                    "message": row["message"],
                    "schedule": row["schedule_type"],
                    "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
                    "created_at": row["created_at"],
                    "status": "active" if job else "pending",
                }
            )
    return reminders


def update_reminder(config: Config, scheduler: BackgroundScheduler, *, reminder_id: str, message: str, notif_dir: Path | None = None) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        reminder = cursor.fetchone()
        if not reminder:
            raise ValueError(f"Reminder '{reminder_id}' not found. Use list to see active reminders.")
        conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        conn.commit()

    job = scheduler.get_job(reminder_id)
    if job:
        job.modify(args=[reminder_id], kwargs={"message": message, "data_dir": config.data_dir, "notif_dir": str(notif_dir) if notif_dir else ""})

    return {
        "id": reminder_id,
        "message": message,
        "schedule": reminder["schedule_type"],
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "status": "updated",
    }


def cancel_reminder(config: Config, scheduler: BackgroundScheduler, *, reminder_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT 1 FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        if not cursor.fetchone():
            raise ValueError(f"Reminder '{reminder_id}' not found")
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()

    try:
        scheduler.remove_job(reminder_id)
    except JobLookupError:
        pass

    return {"status": "cancelled", "id": reminder_id}
