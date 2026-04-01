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

from .config import Config
from . import db
from .scheduler import write_reminder_notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _to_utc_dt(datetime_str: str, timezone_str: str) -> datetime:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        local_tz = ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: '{timezone_str}'. Use IANA names like 'Europe/London' or 'America/New_York'.")

    naive = datetime.fromisoformat(datetime_str.replace("Z", "+00:00"))
    if naive.tzinfo is not None:
        return naive.astimezone(UTC)
    return naive.replace(tzinfo=local_tz).astimezone(UTC)


def _to_utc(datetime_str: str, timezone_str: str) -> str:
    return _to_utc_dt(datetime_str, timezone_str).isoformat()


def normalize_priority(priority: int | str) -> int:
    if isinstance(priority, int):
        if priority not in (1, 2, 3):
            raise ValueError(f"Priority must be 1-3 or 'low'/'normal'/'high', got {priority}")
        return priority
    if isinstance(priority, str) and priority.isdigit():
        return normalize_priority(int(priority))
    priority_map = {"low": 1, "normal": 2, "high": 3}
    key = priority.lower()
    if key not in priority_map:
        raise ValueError(f"Priority must be 1-3 or 'low'/'normal'/'high', got '{priority}'")
    return priority_map[key]


def _compute_due_date(
    due_datetime: str | None,
    timezone_str: str | None,
    due_in_minutes: int | None,
    due_in_hours: int | None,
    due_in_days: int | None,
) -> str | None:
    if due_datetime is not None:
        if timezone_str is None:
            raise ValueError("timezone is required when due_datetime is provided")
        return _to_utc(due_datetime, timezone_str)

    for name, val in [("due_in_minutes", due_in_minutes), ("due_in_hours", due_in_hours), ("due_in_days", due_in_days)]:
        if val is not None and val <= 0:
            raise ValueError(f"{name} must be positive")

    offset = timedelta(
        minutes=due_in_minutes or 0,
        hours=due_in_hours or 0,
        days=due_in_days or 0,
    )
    if offset.total_seconds() > 0:
        return (_now_utc() + offset).isoformat()

    return None


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def _get_metadata_path(data_dir: Path, task_id: str) -> Path:
    return data_dir / "metadata" / f"{task_id}.md"


def _read_metadata(data_dir: Path, task_id: str) -> str | None:
    try:
        return _get_metadata_path(data_dir, task_id).read_text()
    except OSError:
        return None


def _write_metadata(data_dir: Path, task_id: str, content: str):
    metadata_dir = data_dir / "metadata"
    metadata_dir.mkdir(exist_ok=True)
    _get_metadata_path(data_dir, task_id).write_text(content)


def _delete_metadata(data_dir: Path, task_id: str):
    _get_metadata_path(data_dir, task_id).unlink(missing_ok=True)


def _task_with_metadata(data_dir: Path, row: dict, include_content: bool = False) -> dict:
    task = dict(row)
    task_id = task["id"]
    task["metadata_path"] = str(_get_metadata_path(data_dir, task_id))
    if include_content:
        task["metadata_content"] = _read_metadata(data_dir, task_id)
    return task


# ---------------------------------------------------------------------------
# Task commands
# ---------------------------------------------------------------------------


def add_task(
    config: Config,
    *,
    title: str,
    due_datetime: str | None = None,
    timezone: str | None = None,
    due_in_minutes: int | None = None,
    due_in_hours: int | None = None,
    due_in_days: int | None = None,
    priority: int | str = 2,
    initial_metadata: str | None = None,
) -> dict:
    priority = normalize_priority(priority)
    task_id = str(uuid.uuid4())[:8]
    due_date = _compute_due_date(due_datetime, timezone, due_in_minutes, due_in_hours, due_in_days)

    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, priority, due_date) VALUES (?, ?, ?, ?)",
            (task_id, title, priority, due_date),
        )
        if due_date:
            db.create_auto_reminders(conn, task_id, title, due_date, priority)
        conn.commit()

    if initial_metadata:
        _write_metadata(config.data_dir, task_id, initial_metadata)

    return {
        "id": task_id,
        "title": title,
        "status": "pending",
        "priority": priority,
        "due_date": due_date,
        "metadata_path": str(_get_metadata_path(config.data_dir, task_id)),
    }


def list_tasks(config: Config, *, show_completed: bool = False) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        query = "SELECT * FROM tasks"
        if not show_completed:
            query += " WHERE status != 'done'"
        query += " ORDER BY priority DESC, due_date ASC NULLS LAST, created_at DESC"
        cursor = conn.execute(query)
        return [_task_with_metadata(config.data_dir, dict(row), include_content=False) for row in cursor]


def update_task(
    config: Config,
    *,
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    priority: int | str | None = None,
) -> dict:
    if status and status not in ("pending", "done"):
        raise ValueError(f"Status must be pending or done, got {status}")
    if priority is not None:
        priority = normalize_priority(priority)

    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Task '{task_id}' not found. Use list to see available tasks.")

        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status == "done":
                updates.append("completed_at = ?")
                params.append(_now_utc().isoformat())
                db.delete_auto_reminders(conn, task_id)
            elif status == "pending":
                updates.append("completed_at = NULL")
                # Recreate auto-reminders if task has a due date and is reopened
                old_due = result["due_date"]
                if old_due:
                    db.create_auto_reminders(conn, task_id, result["title"], old_due, result["priority"])

        for field, value in [("title", title), ("priority", priority)]:
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if updates:
            params.append(task_id)
            query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)
            conn.commit()

        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _task_with_metadata(config.data_dir, dict(cursor.fetchone()), include_content=True)


def get_task(config: Config, *, task_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Task '{task_id}' not found. Use list to see available tasks.")
        return _task_with_metadata(config.data_dir, dict(result), include_content=True)


def delete_task(config: Config, *, task_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not cursor.fetchone():
            raise ValueError(f"Task '{task_id}' not found. Use list to see available tasks.")
        # FK CASCADE handles linked reminders automatically
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    _delete_metadata(config.data_dir, task_id)
    return {"status": "deleted", "task_id": task_id}


def search_tasks(config: Config, *, query: str, show_completed: bool = False) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        sql = "SELECT * FROM tasks WHERE title LIKE ?"
        if not show_completed:
            sql += " AND status != 'done'"
        sql += " ORDER BY priority DESC, due_date ASC NULLS LAST, created_at DESC"
        cursor = conn.execute(sql, (f"%{query}%",))
        return [_task_with_metadata(config.data_dir, dict(row), include_content=False) for row in cursor]


# ---------------------------------------------------------------------------
# Reminder job callback
# ---------------------------------------------------------------------------


def send_reminder_job(reminder_id: str, *, message: str, data_dir: str, notif_dir: str):
    """Called by APScheduler when a reminder fires."""
    data_dir = Path(data_dir)

    if notif_dir:
        task_id = None
        with closing(db.get_db(data_dir)) as conn:
            cursor = conn.execute("SELECT task_id, message, trigger_data FROM reminders WHERE id = ?", (reminder_id,))
            row = cursor.fetchone()
            if row:
                task_id = row["task_id"]
                message = row["message"] or message
                trigger_data = json.loads(row["trigger_data"]) if row["trigger_data"] else {}

                logger.info(f"Firing reminder {reminder_id}: {message[:50]}")

                write_reminder_notification(
                    Path(notif_dir),
                    reminder_id,
                    message,
                    task_id=task_id,
                )

                if "type" in trigger_data and trigger_data["type"] == "date":
                    conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                    conn.commit()


# ---------------------------------------------------------------------------
# Reminder restore (for daemon startup + missed reminder handling)
# ---------------------------------------------------------------------------


def _restore_row(scheduler: BackgroundScheduler, row, now: datetime, notif_dir: Path | None, conn, config: Config) -> bool:
    """Restore a single reminder row into the scheduler. Returns True if handled, False to skip."""
    reminder_id = row["id"]
    try:
        trigger_data: TriggerData = json.loads(row["trigger_data"])
        trigger_type = trigger_data["type"] if "type" in trigger_data else None

        if trigger_type == "date":
            if "run_date" not in trigger_data:
                logger.warning(f"Reminder {reminder_id}: date trigger missing 'run_date', skipping")
                return False
            run_date = db.parse_datetime(trigger_data["run_date"])
            if run_date < now:
                logger.info(f"Reminder {reminder_id}: past due, sending missed notification")
                if notif_dir:
                    write_reminder_notification(
                        notif_dir,
                        reminder_id,
                        row["message"],
                        task_id=row["task_id"],
                        extra={"missed": True},
                    )
                conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                return True
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
            trigger = IntervalTrigger(hours=trigger_data["hours"] if "hours" in trigger_data else 1)

        else:
            logger.warning(f"Reminder {reminder_id}: unknown trigger type '{trigger_type}', skipping")
            return False

        scheduler.add_job(
            func=send_reminder_job,
            trigger=trigger,
            args=[reminder_id],
            kwargs={
                "message": row["message"],
                "data_dir": str(config.data_dir),
                "notif_dir": str(notif_dir) if notif_dir else "",
            },
            id=reminder_id,
            replace_existing=True,
        )
        logger.info(f"Restored reminder {reminder_id} ({trigger_type})")
        return True

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Failed to restore reminder {reminder_id}: {e}")
        return False


def restore_all_jobs(config: Config, scheduler: BackgroundScheduler, *, notif_dir: Path | None = None):
    """Load all active reminders from DB and register as APScheduler jobs.
    Past-due one-time reminders fire missed notifications immediately."""
    now = _now_utc()
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT id, task_id, message, trigger_data FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL")
        for row in cursor:
            _restore_row(scheduler, row, now, notif_dir, conn, config)
        conn.commit()


def restore_jobs_by_ids(config: Config, scheduler: BackgroundScheduler, ids: set[str], *, notif_dir: Path | None = None):
    """Restore specific reminder IDs from DB into the scheduler."""
    now = _now_utc()
    placeholders = ",".join("?" for _ in ids)
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute(
            f"SELECT id, task_id, message, trigger_data FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL AND id IN ({placeholders})",
            list(ids),
        )
        for row in cursor:
            _restore_row(scheduler, row, now, notif_dir, conn, config)
        conn.commit()


# ---------------------------------------------------------------------------
# Reminder commands (CRUD)
# ---------------------------------------------------------------------------


def remind_set(
    config: Config,
    *,
    message: str,
    task_id: str | None = None,
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
        schedule_info = "hourly"
        trigger_data = {"type": "interval", "hours": 1}
        next_run = None
    elif recurring in ("daily", "weekly", "monthly", "yearly"):
        if not scheduled_datetime or not tz:
            raise ValueError(f"scheduled_datetime and tz are required for {recurring} reminders")
        utc_dt = _to_utc_dt(scheduled_datetime, tz)
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
        next_run = trigger.get_next_fire_time(None, _now_utc())
    elif scheduled_datetime:
        if not tz:
            raise ValueError("tz is required when scheduled_datetime is provided")
        utc_dt = _to_utc_dt(scheduled_datetime, tz)
        schedule_info = f"once at {utc_dt.isoformat()}"
        trigger_data = {"type": "date", "run_date": utc_dt.isoformat()}
        next_run = utc_dt
    else:
        for name, val in [("in_minutes", in_minutes), ("in_hours", in_hours), ("in_days", in_days)]:
            if val is not None and val <= 0:
                raise ValueError(f"{name} must be positive")
        offset = timedelta(minutes=in_minutes or 0, hours=in_hours or 0, days=in_days or 0)
        if not offset.total_seconds():
            raise ValueError("Must specify when to send reminder")
        run_time = _now_utc() + offset
        parts = [f"{v} {u}" for v, u in [(in_days, "days"), (in_hours, "hours"), (in_minutes, "minutes")] if v]
        schedule_info = f"once (in {' '.join(parts)})"
        trigger_data = {"type": "date", "run_date": run_time.isoformat()}
        next_run = run_time

    with closing(db.get_db(config.data_dir)) as conn:
        if task_id is not None:
            cursor = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,))
            if not cursor.fetchone():
                raise ValueError(f"Task '{task_id}' not found")

        conn.execute(
            """INSERT OR REPLACE INTO reminders
               (id, task_id, message, schedule_type, scheduled_time, completed, trigger_data, auto_generated)
               VALUES (?, ?, ?, ?, ?, 0, ?, 0)""",
            (
                reminder_id,
                task_id,
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
        "task_id": task_id,
        "schedule": schedule_info,
        "next_run": next_run.isoformat() if next_run else None,
        "created_at": created_at,
        "status": "scheduled",
    }


def remind_list(config: Config, *, task_id: str | None = None, limit: int = 50) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        if task_id is not None:
            cursor = conn.execute(
                "SELECT * FROM reminders WHERE completed = 0 AND task_id = ? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM reminders WHERE completed = 0 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "message": row["message"],
                "schedule": row["schedule_type"],
                "next_run": row["scheduled_time"],
                "created_at": row["created_at"],
                "auto_generated": bool(row["auto_generated"]),
                "status": "pending",
            }
            for row in cursor
        ]


def remind_delete(config: Config, *, reminder_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT 1 FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        if not cursor.fetchone():
            raise ValueError(f"Reminder '{reminder_id}' not found")
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()

    return {"status": "deleted", "id": reminder_id}


def remind_update(config: Config, *, reminder_id: str, message: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        reminder = cursor.fetchone()
        if not reminder:
            raise ValueError(f"Reminder '{reminder_id}' not found. Use 'tasks remind list' to see active reminders.")
        conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        conn.commit()

    return {
        "id": reminder_id,
        "message": message,
        "schedule": reminder["schedule_type"],
        "next_run": reminder["scheduled_time"],
        "status": "updated",
    }
