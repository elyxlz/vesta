from datetime import datetime as dt, timedelta, UTC
from contextlib import closing, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import TypedDict
import argparse
import json
import logging
import sqlite3
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from .scheduler import write_notification

logger = logging.getLogger(__name__)


class TriggerData(TypedDict, total=False):
    type: str  # "date", "cron", or "interval"
    # For date triggers
    run_date: str
    # For cron triggers
    month: int
    day: int
    day_of_week: str
    hour: int
    minute: int
    # For interval triggers
    hours: int


def _now_utc() -> dt:
    return dt.now(UTC)


def _parse_datetime(dt_str: str) -> dt:
    """Parse datetime string to timezone-aware datetime (assumes UTC if naive)."""
    parsed = dt.fromisoformat(dt_str.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _validate_directory(path_str: str | None, *, param_name: str) -> Path:
    """Validate and prepare a directory parameter"""
    if not path_str:
        raise ValueError(f"Error: --{param_name} is required")

    path = Path(path_str).resolve()
    path.mkdir(parents=True, exist_ok=True)

    # Test writability
    test_file = path / ".write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        raise RuntimeError(f"Error: --{param_name} directory is not writable: {path} ({e})")

    return path


@dataclass
class ReminderContext:
    scheduler: BackgroundScheduler
    data_dir: Path
    log_dir: Path
    notif_dir: Path


def _setup_file_logging(log_dir: Path) -> None:
    """Configure file logging to log_dir/reminder-mcp.log"""
    log_file = log_dir / "reminder-mcp.log"
    handler = logging.FileHandler(log_file)
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


@asynccontextmanager
async def reminder_lifespan(server: FastMCP) -> AsyncIterator[ReminderContext]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--log-dir", type=str, required=True)
    parser.add_argument("--notifications-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    data_dir = _validate_directory(args.data_dir, param_name="data-dir")
    log_dir = _validate_directory(args.log_dir, param_name="log-dir")
    notif_dir = _validate_directory(args.notifications_dir, param_name="notifications-dir")

    _setup_file_logging(log_dir)

    from . import scheduler as scheduler_module

    scheduler = scheduler_module.create_scheduler(data_dir)
    scheduler.start()

    ctx = ReminderContext(scheduler, data_dir, log_dir, notif_dir)
    init_db(ctx)
    restore_all_jobs(ctx)

    try:
        yield ctx
    finally:
        scheduler.shutdown(wait=True)


mcp = FastMCP("reminder-mcp", lifespan=reminder_lifespan)


def get_db(ctx: ReminderContext):
    conn = sqlite3.connect(ctx.data_dir / "reminders.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(ctx: ReminderContext):
    with closing(get_db(ctx)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                schedule_type TEXT,
                scheduled_time TEXT,
                completed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                trigger_data TEXT
            )
        """)
        conn.commit()

        # Migrations
        cursor = conn.execute("PRAGMA table_info(reminders)")
        columns = {row[1] for row in cursor.fetchall()}

        if "trigger_data" not in columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN trigger_data TEXT")
            conn.commit()

        # Migrate fired → completed
        if "fired" in columns and "completed" not in columns:
            conn.execute("ALTER TABLE reminders RENAME COLUMN fired TO completed")
            conn.commit()
            logger.info("Migrated 'fired' column to 'completed'")

        # Clean up orphan APScheduler jobstore table
        conn.execute("DROP TABLE IF EXISTS apscheduler_jobs")


def send_reminder_job(reminder_id: str, *, message: str, data_dir: Path, notif_dir: Path):
    msg_preview = message[:50] + "..." if len(message) > 50 else message
    logger.info(f"Firing reminder {reminder_id}: {msg_preview}")
    write_notification(notif_dir, reminder_id, message)

    conn = sqlite3.connect(data_dir / "reminders.db")
    conn.row_factory = sqlite3.Row
    with closing(conn):
        # Check if one-time reminder (type=date) - only mark those as completed
        cursor = conn.execute("SELECT trigger_data FROM reminders WHERE id = ?", (reminder_id,))
        row = cursor.fetchone()
        if row and row["trigger_data"]:
            trigger_data = json.loads(row["trigger_data"])
            if trigger_data.get("type") == "date":
                conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                conn.commit()


def restore_all_jobs(ctx: ReminderContext):
    """Restore all active reminders from database to scheduler on startup."""
    now = _now_utc()
    with closing(get_db(ctx)) as conn:
        cursor = conn.execute("SELECT id, message, trigger_data FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL")

        for row in cursor:
            reminder_id = row["id"]
            try:
                trigger_data: TriggerData = json.loads(row["trigger_data"])
                trigger_type = trigger_data.get("type")

                if trigger_type == "date":
                    # One-time reminder - check if past due
                    run_date_str = trigger_data.get("run_date")
                    if not run_date_str:
                        logger.warning(f"Reminder {reminder_id}: date trigger missing 'run_date', skipping")
                        continue

                    run_date = _parse_datetime(run_date_str)
                    if run_date < now:
                        # Past due - send missed notification, mark completed
                        logger.info(f"Reminder {reminder_id}: past due, sending missed notification")
                        write_notification(ctx.notif_dir, reminder_id, row["message"], data={"missed": True})
                        conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                        continue

                    # Future - schedule it
                    trigger = DateTrigger(run_date=run_date)

                elif trigger_type == "cron":
                    trigger = CronTrigger(
                        month=trigger_data.get("month"),
                        day=trigger_data.get("day"),
                        day_of_week=trigger_data.get("day_of_week"),
                        hour=trigger_data.get("hour"),
                        minute=trigger_data.get("minute"),
                    )

                elif trigger_type == "interval":
                    if "hours" not in trigger_data:
                        logger.warning(f"Reminder {reminder_id}: interval trigger missing 'hours', using default 1")
                    trigger = IntervalTrigger(hours=trigger_data.get("hours", 1))

                else:
                    logger.warning(f"Reminder {reminder_id}: unknown trigger type '{trigger_type}', skipping")
                    continue

                ctx.scheduler.add_job(
                    func=send_reminder_job,
                    trigger=trigger,
                    args=[reminder_id],
                    kwargs={"message": row["message"], "data_dir": ctx.data_dir, "notif_dir": ctx.notif_dir},
                    id=reminder_id,
                    replace_existing=True,
                )
                logger.info(f"Restored reminder {reminder_id} ({trigger_type})")

            except (json.JSONDecodeError, KeyError, ValueError) as e:
                logger.error(f"Failed to restore reminder {reminder_id}: {e}")

        conn.commit()


def _to_utc(datetime_str: str, timezone_str: str) -> dt:
    """Convert datetime string with timezone to UTC datetime object."""
    from zoneinfo import ZoneInfo

    # Parse the datetime
    naive_dt = dt.fromisoformat(datetime_str.replace("Z", "+00:00"))

    # If already has timezone info, convert to UTC
    if naive_dt.tzinfo is not None:
        return naive_dt.astimezone(UTC)

    # Apply the provided timezone and convert to UTC
    local_tz = ZoneInfo(timezone_str)
    local_dt = naive_dt.replace(tzinfo=local_tz)
    return local_dt.astimezone(UTC)


@mcp.tool()
def set_reminder(
    ctx: Context,
    *,
    message: str,
    # Absolute time (requires timezone)
    scheduled_datetime: str | None = None,
    tz: str | None = None,
    # Relative time (uses UTC internally)
    in_minutes: int | None = None,
    in_hours: int | None = None,
    in_days: int | None = None,
    # Recurring (requires scheduled_datetime + tz to extract pattern)
    recurring: str | None = None,
) -> dict:
    """scheduled_datetime: ISO-8601 (requires tz). in_*: relative offset (UTC). recurring: 'hourly'/'daily'/'weekly'/'monthly'/'yearly' (extracts time from scheduled_datetime)."""
    context: ReminderContext = ctx.request_context.lifespan_context

    reminder_id = str(uuid.uuid4())[:8]
    trigger_data = None

    if recurring == "hourly":
        trigger = IntervalTrigger(hours=1)
        schedule_info = "hourly"
        trigger_data = {"type": "interval", "hours": 1}
    elif recurring in ("daily", "weekly", "monthly", "yearly"):
        if not scheduled_datetime or not tz:
            raise ValueError(f"scheduled_datetime and tz are required for {recurring} reminders (to extract time pattern)")
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
        else:  # yearly
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
        offset = timedelta(minutes=in_minutes or 0, hours=in_hours or 0, days=in_days or 0)

        if not offset.total_seconds():
            raise ValueError("Must specify when to send reminder")

        run_time = _now_utc() + offset
        trigger = DateTrigger(run_date=run_time)

        parts = [f"{v} {u}" for v, u in [(in_days, "days"), (in_hours, "hours"), (in_minutes, "minutes")] if v]
        schedule_info = f"once (in {' '.join(parts)})"
        trigger_data = {"type": "date", "run_date": run_time.isoformat()}

    context.scheduler.add_job(
        func=send_reminder_job,
        trigger=trigger,
        args=[reminder_id],
        kwargs={"message": message, "data_dir": context.data_dir, "notif_dir": context.notif_dir},
        id=reminder_id,
        replace_existing=True,
    )

    job = context.scheduler.get_job(reminder_id)
    next_run = job.next_run_time if job else None

    with closing(get_db(context)) as conn:
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


@mcp.tool()
def list_reminders(ctx: Context, *, limit: int = 50) -> list[dict]:
    """List active reminders."""
    context: ReminderContext = ctx.request_context.lifespan_context
    jobs = {job.id: job for job in context.scheduler.get_jobs()}

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE completed = 0 ORDER BY created_at DESC LIMIT ?", (limit,))
        reminders = []

        for row in cursor:
            job = jobs.get(row["id"])
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


@mcp.tool()
def update_reminder(ctx: Context, *, reminder_id: str, message: str) -> dict:
    """Update a reminder's message"""
    context: ReminderContext = ctx.request_context.lifespan_context

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        reminder = cursor.fetchone()

        if not reminder:
            raise ValueError(f"Reminder '{reminder_id}' not found. Use list_reminders() to see active reminders.")

        conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        conn.commit()

    job = context.scheduler.get_job(reminder_id)
    if job:
        job.modify(args=[reminder_id], kwargs={"message": message, "data_dir": context.data_dir, "notif_dir": context.notif_dir})

    return {
        "id": reminder_id,
        "message": message,
        "schedule": reminder["schedule_type"],
        "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "status": "updated",
    }


@mcp.tool()
def cancel_reminder(ctx: Context, *, reminder_id: str) -> dict:
    """Cancel a scheduled reminder."""
    context: ReminderContext = ctx.request_context.lifespan_context

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT 1 FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        if not cursor.fetchone():
            raise ValueError(f"Reminder '{reminder_id}' not found")

        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()

    try:
        context.scheduler.remove_job(reminder_id)
    except JobLookupError:
        pass

    return {"status": "cancelled", "id": reminder_id}
