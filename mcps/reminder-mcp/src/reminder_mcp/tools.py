from datetime import datetime as dt, timedelta
from contextlib import closing, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
import argparse
import sqlite3
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from .scheduler import write_notification


@dataclass
class ReminderContext:
    scheduler: BackgroundScheduler
    data_dir: Path
    notif_dir: Path


@asynccontextmanager
async def reminder_lifespan(server: FastMCP) -> AsyncIterator[ReminderContext]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--notifications-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    notif_dir = Path(args.notifications_dir).resolve()
    notif_dir.mkdir(parents=True, exist_ok=True)

    from . import scheduler as scheduler_module

    scheduler = scheduler_module.create_scheduler(data_dir)
    scheduler.start()

    ctx = ReminderContext(scheduler, data_dir, notif_dir)
    init_db(ctx)
    check_missed_reminders(ctx)

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
                fired INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def send_reminder_job(reminder_id: str, message: str, data_dir: Path, notif_dir: Path):
    write_notification(notif_dir, reminder_id, message)
    conn = sqlite3.connect(data_dir / "reminders.db")
    conn.row_factory = sqlite3.Row
    with closing(conn):
        conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
        conn.commit()


def check_missed_reminders(ctx: ReminderContext):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    with closing(get_db(ctx)) as conn:
        cursor = conn.execute(
            "SELECT id, message, scheduled_time FROM reminders WHERE fired = 0 AND scheduled_time < ?",
            (now,),
        )
        for row in cursor:
            write_notification(
                ctx.notif_dir,
                row["id"],
                row["message"],
                {"missed": True, "scheduled_time": row["scheduled_time"]},
            )
            conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],))
        conn.commit()


def parse_time(time_str: str) -> tuple[int, int]:
    try:
        return tuple(map(int, time_str.split(":")))
    except ValueError:
        raise ValueError("Time must be in HH:MM format")


@mcp.tool()
def set_reminder(
    ctx: Context,
    message: str,
    scheduled_datetime: str | None = None,
    seconds: float | None = None,
    minutes: float | None = None,
    hours: float | None = None,
    days: float | None = None,
    recurring: str | None = None,
    day_of_week: str | None = None,
    time: str | None = None,
) -> dict:
    """Set a reminder with flexible scheduling options.

    Examples:
    - One-time (specific): scheduled_datetime="2024-01-15T14:00:00"
    - One-time (relative): minutes=30 OR hours=2 OR days=1
    - Daily: recurring="daily", time="09:00" (24-hour format, defaults to 09:00)
    - Weekly: recurring="weekly", day_of_week="Monday", time="09:00"
    - Hourly: recurring="hourly"
    """
    context: ReminderContext = ctx.request_context.lifespan_context

    reminder_id = str(uuid.uuid4())[:8]

    if recurring == "daily":
        h, m = parse_time(time) if time else (9, 0)
        trigger = CronTrigger(hour=h, minute=m)
        schedule_info = "daily" + (f" at {time}" if time else "")
    elif recurring == "hourly":
        trigger = IntervalTrigger(hours=1)
        schedule_info = "hourly"
    elif recurring == "weekly" and day_of_week:
        h, m = parse_time(time) if time else (9, 0)
        trigger = CronTrigger(day_of_week=day_of_week[:3].lower(), hour=h, minute=m)
        schedule_info = f"weekly on {day_of_week}" + (f" at {time}" if time else "")
    elif scheduled_datetime:
        trigger = DateTrigger(run_date=dt.fromisoformat(scheduled_datetime))
        schedule_info = f"once at {scheduled_datetime}"
    else:
        offset = timedelta(seconds=seconds or 0, minutes=minutes or 0, hours=hours or 0, days=days or 0)

        if not offset:
            raise ValueError("Must specify when to send reminder")

        run_time = dt.now() + offset
        trigger = DateTrigger(run_date=run_time)

        parts = [f"{v} {u}" for v, u in [(days, "days"), (hours, "hours"), (minutes, "minutes"), (seconds, "seconds")] if v]
        schedule_info = f"once (in {' '.join(parts)})"

    context.scheduler.add_job(
        func=send_reminder_job,
        trigger=trigger,
        args=[reminder_id, message, context.data_dir, context.notif_dir],
        id=reminder_id,
        replace_existing=True,
    )

    next_run = context.scheduler.get_job(reminder_id).next_run_time

    with closing(get_db(context)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reminders (id, message, schedule_type, scheduled_time, fired) VALUES (?, ?, ?, ?, 0)",
            (
                reminder_id,
                message,
                schedule_info,
                next_run.isoformat() if next_run else None,
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
def list_reminders(ctx: Context, limit: int = 50) -> list[dict]:
    """List scheduled reminders (limit: max number to return, default 50)"""
    context: ReminderContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM reminders")
        reminder_data = {row["id"]: dict(row) for row in cursor}

    reminders = [
        {
            "id": job.id,
            "message": reminder_data[job.id]["message"],
            "schedule": reminder_data[job.id]["schedule_type"],
            "next_run": (job.next_run_time.isoformat() if job.next_run_time else None),
            "created_at": reminder_data[job.id]["created_at"],
            "status": "active" if job.next_run_time else "paused",
        }
        for job in context.scheduler.get_jobs()
        if job.id in reminder_data
    ]

    return reminders[:limit]


@mcp.tool()
def update_reminder(ctx: Context, reminder_id: str, message: str) -> dict:
    """Update a reminder's message"""
    context: ReminderContext = ctx.request_context.lifespan_context

    job = context.scheduler.get_job(reminder_id)
    if not job:
        raise ValueError(f"Reminder '{reminder_id}' not found. Use list_reminders() to see active reminders.")

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        reminder = cursor.fetchone()
        if not reminder:
            raise ValueError(f"Reminder '{reminder_id}' not found in database")

        conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        conn.commit()

    job.modify(args=[reminder_id, message, context.data_dir, context.notif_dir])

    return {
        "id": reminder_id,
        "message": message,
        "schedule": reminder["schedule_type"],
        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        "status": "updated",
    }


@mcp.tool()
def cancel_reminder(ctx: Context, reminder_id: str) -> dict:
    """Cancel a scheduled reminder"""
    context: ReminderContext = ctx.request_context.lifespan_context
    from apscheduler.jobstores.base import JobLookupError

    try:
        context.scheduler.remove_job(reminder_id)
    except JobLookupError:
        raise ValueError(f"Reminder '{reminder_id}' not found. Use list_reminders() to see active reminders.")

    with closing(get_db(context)) as conn:
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()

    return {"status": "cancelled", "id": reminder_id}
