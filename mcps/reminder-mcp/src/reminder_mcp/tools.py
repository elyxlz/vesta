from datetime import datetime as dt, timedelta, timezone
from contextlib import closing, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
import argparse
import json
import re
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


def _now_utc() -> dt:
    return dt.now(timezone.utc)


def _parse_datetime(dt_str: str) -> dt:
    """Parse datetime string to timezone-aware datetime (assumes UTC if naive)."""
    parsed = dt.fromisoformat(dt_str.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


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

    from . import scheduler as scheduler_module

    scheduler = scheduler_module.create_scheduler(data_dir)
    scheduler.start()

    ctx = ReminderContext(scheduler, data_dir, log_dir, notif_dir)
    init_db(ctx)
    restore_all_jobs(ctx)
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


def migrate_existing_reminders(conn: sqlite3.Connection):
    """Migrate existing reminders to add trigger_data from schedule_type"""
    cursor = conn.execute("SELECT id, schedule_type FROM reminders WHERE trigger_data IS NULL AND fired = 0")
    for row in cursor:
        schedule_type = row["schedule_type"]
        if not schedule_type:
            continue

        trigger_data = None

        if "daily" in schedule_type:
            match = re.search(r"at (\d{1,2}):(\d{2})", schedule_type)
            h, m = (int(match.group(1)), int(match.group(2))) if match else (9, 0)
            trigger_data = {"type": "cron", "hour": h, "minute": m}

        elif "weekly" in schedule_type:
            days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
            day = next((d for d in days if d in schedule_type.lower()), None)
            if day:
                match = re.search(r"at (\d{1,2}):(\d{2})", schedule_type)
                h, m = (int(match.group(1)), int(match.group(2))) if match else (9, 0)
                trigger_data = {"type": "cron", "day_of_week": day[:3], "hour": h, "minute": m}

        elif "hourly" in schedule_type:
            trigger_data = {"type": "interval", "hours": 1}

        elif "once" in schedule_type:
            continue

        if trigger_data:
            conn.execute("UPDATE reminders SET trigger_data = ? WHERE id = ?", (json.dumps(trigger_data), row["id"]))

    conn.commit()


def init_db(ctx: ReminderContext):
    with closing(get_db(ctx)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                schedule_type TEXT,
                scheduled_time TEXT,
                fired INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                trigger_data TEXT
            )
        """)
        conn.commit()

        cursor = conn.execute("PRAGMA table_info(reminders)")
        columns = {row[1] for row in cursor.fetchall()}
        if "trigger_data" not in columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN trigger_data TEXT")
            conn.commit()

        migrate_existing_reminders(conn)


def send_reminder_job(reminder_id: str, *, message: str, data_dir: Path, notif_dir: Path):
    write_notification(notif_dir, reminder_id, message)
    conn = sqlite3.connect(data_dir / "reminders.db")
    conn.row_factory = sqlite3.Row
    with closing(conn):
        conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
        conn.commit()


def check_missed_reminders(ctx: ReminderContext):
    now = _now_utc()
    with closing(get_db(ctx)) as conn:
        cursor = conn.execute("SELECT id, message, scheduled_time FROM reminders WHERE fired = 0 AND scheduled_time IS NOT NULL")
        for row in cursor:
            if _parse_datetime(row["scheduled_time"]) < now:
                write_notification(ctx.notif_dir, row["id"], row["message"], data={"missed": True})
                conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],))
        conn.commit()


def restore_all_jobs(ctx: ReminderContext):
    """Restore all unfired reminders from database to scheduler"""
    with closing(get_db(ctx)) as conn:
        cursor = conn.execute("SELECT id, message, trigger_data FROM reminders WHERE fired = 0 AND trigger_data IS NOT NULL")

        for row in cursor:
            try:
                trigger_data = json.loads(row["trigger_data"])
                trigger_type = trigger_data.get("type")

                if trigger_type == "cron":
                    trigger = CronTrigger(
                        day_of_week=trigger_data.get("day_of_week"),
                        hour=trigger_data.get("hour"),
                        minute=trigger_data.get("minute"),
                    )
                elif trigger_type == "interval":
                    trigger = IntervalTrigger(hours=trigger_data.get("hours", 1))
                else:
                    continue

                ctx.scheduler.add_job(
                    func=send_reminder_job,
                    trigger=trigger,
                    args=[row["id"]],
                    kwargs={"message": row["message"], "data_dir": ctx.data_dir, "notif_dir": ctx.notif_dir},
                    id=row["id"],
                    replace_existing=True,
                )
            except (json.JSONDecodeError, KeyError, ValueError):
                pass


def parse_time(time_str: str) -> tuple[int, int]:
    try:
        parts = tuple(map(int, time_str.split(":")))
        if len(parts) != 2:
            raise ValueError("Time must be in HH:MM format")
        return parts  # type: ignore
    except ValueError:
        raise ValueError("Time must be in HH:MM format")


@mcp.tool()
def set_reminder(
    ctx: Context,
    *,
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
    trigger_data = None

    if recurring == "daily":
        h, m = parse_time(time) if time else (9, 0)
        trigger = CronTrigger(hour=h, minute=m)
        schedule_info = "daily" + (f" at {time}" if time else "")
        trigger_data = {"type": "cron", "hour": h, "minute": m}
    elif recurring == "hourly":
        trigger = IntervalTrigger(hours=1)
        schedule_info = "hourly"
        trigger_data = {"type": "interval", "hours": 1}
    elif recurring == "weekly" and day_of_week:
        h, m = parse_time(time) if time else (9, 0)
        trigger = CronTrigger(day_of_week=day_of_week[:3].lower(), hour=h, minute=m)
        schedule_info = f"weekly on {day_of_week}" + (f" at {time}" if time else "")
        trigger_data = {"type": "cron", "day_of_week": day_of_week[:3].lower(), "hour": h, "minute": m}
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
        args=[reminder_id],
        kwargs={"message": message, "data_dir": context.data_dir, "notif_dir": context.notif_dir},
        id=reminder_id,
        replace_existing=True,
    )

    job = context.scheduler.get_job(reminder_id)
    next_run = job.next_run_time if job else None

    with closing(get_db(context)) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reminders (id, message, schedule_type, scheduled_time, fired, trigger_data) VALUES (?, ?, ?, ?, 0, ?)",
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


def _is_stale(scheduled_time_str: str | None, has_job: bool, now: dt) -> bool:
    """One-time reminder is stale if past due with no active job."""
    if has_job or not scheduled_time_str:
        return False
    return _parse_datetime(scheduled_time_str) < now


@mcp.tool()
def list_reminders(ctx: Context, limit: int = 50, include_past: bool = False) -> list[dict]:
    """List scheduled reminders."""
    context: ReminderContext = ctx.request_context.lifespan_context
    now = _now_utc()
    jobs = {job.id: job for job in context.scheduler.get_jobs()}

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE fired = 0 ORDER BY created_at DESC LIMIT ?", (limit,))
        reminders = []

        for row in cursor:
            job = jobs.get(row["id"])
            is_stale = _is_stale(row["scheduled_time"], job is not None, now)

            if is_stale and not include_past:
                conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],))
                continue

            reminders.append({
                "id": row["id"],
                "message": row["message"],
                "schedule": row["schedule_type"],
                "next_run": job.next_run_time.isoformat() if job and job.next_run_time else None,
                "created_at": row["created_at"],
                "status": "active" if job else "stale" if is_stale else "pending",
            })

        conn.commit()
    return reminders


@mcp.tool()
def update_reminder(ctx: Context, reminder_id: str, *, message: str) -> dict:
    """Update a reminder's message"""
    context: ReminderContext = ctx.request_context.lifespan_context

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE id = ? AND fired = 0", (reminder_id,))
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
def cancel_reminder(ctx: Context, reminder_id: str) -> dict:
    """Cancel a scheduled reminder."""
    context: ReminderContext = ctx.request_context.lifespan_context

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT 1 FROM reminders WHERE id = ? AND fired = 0", (reminder_id,))
        if not cursor.fetchone():
            raise ValueError(f"Reminder '{reminder_id}' not found")

        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()

    try:
        context.scheduler.remove_job(reminder_id)
    except JobLookupError:
        pass

    return {"status": "cancelled", "id": reminder_id}
