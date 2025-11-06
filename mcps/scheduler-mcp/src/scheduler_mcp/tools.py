from datetime import datetime as dt, timedelta
from contextlib import closing
from dataclasses import dataclass
import sqlite3
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from .scheduler import write_notification

mcp = FastMCP("scheduler-mcp")


@dataclass
class SchedulerContext:
    scheduler: BackgroundScheduler
    data_dir: Path
    notif_dir: Path


_context: SchedulerContext | None = None


def init_tools(scheduler: BackgroundScheduler, data_dir: Path, notif_dir: Path):
    global _context
    _context = SchedulerContext(scheduler, data_dir, notif_dir)
    init_db()
    check_missed_reminders()


def get_db():
    assert _context is not None
    conn = sqlite3.connect(_context.data_dir / "reminders.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_db()) as conn:
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
        """)

        # Add metadata column to existing tasks table if it doesn't exist
        cursor = conn.execute("""
            PRAGMA table_info(tasks)
        """)
        columns = [row[1] for row in cursor.fetchall()]
        if "metadata" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN metadata TEXT")
        conn.commit()


def send_reminder_job(reminder_id: str, message: str):
    """Module-level function for APScheduler to call"""
    assert _context is not None
    write_notification(_context.notif_dir, reminder_id, message)
    with closing(get_db()) as conn:
        conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (reminder_id,))
        conn.commit()


def check_missed_reminders():
    from datetime import datetime, timezone

    assert _context is not None
    now = datetime.now(timezone.utc).isoformat()

    with closing(get_db()) as conn:
        cursor = conn.execute(
            "SELECT id, message, scheduled_time FROM reminders WHERE fired = 0 AND scheduled_time < ?",
            (now,),
        )
        for row in cursor:
            write_notification(
                _context.notif_dir,
                row["id"],
                row["message"],
                {"missed": True, "scheduled_time": row["scheduled_time"]},
            )
            conn.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (row["id"],))
        conn.commit()


def parse_relative_date(date_str: str) -> str | None:
    if not date_str:
        return None

    date_str = date_str.lower().strip()
    now = dt.now()

    if date_str == "today":
        return now.date().isoformat()
    elif date_str == "tomorrow":
        return (now + timedelta(days=1)).date().isoformat()
    elif date_str.startswith("in ") and date_str.endswith(" days"):
        try:
            days = int(date_str[3:-5])
            return (now + timedelta(days=days)).date().isoformat()
        except ValueError:
            pass

    return date_str


@mcp.tool()
def set_reminder(
    message: str,
    datetime: str | None = None,
    seconds: float | None = None,
    minutes: float | None = None,
    hours: float | None = None,
    days: float | None = None,
    recurring: str | None = None,
    day_of_week: str | None = None,
    time: str | None = None,
) -> dict:
    """datetime: ISO-8601 format. time: HH:MM format. recurring: 'daily', 'hourly', or 'weekly'"""

    reminder_id = str(uuid.uuid4())[:8]
    schedule_info = None

    if recurring == "daily":
        if time:
            try:
                h, m = map(int, time.split(":"))
            except ValueError:
                raise ValueError("Time must be in HH:MM format")
        else:
            h, m = 9, 0
        trigger = CronTrigger(hour=h, minute=m)
        schedule_info = "daily" + (f" at {time}" if time else "")
    elif recurring == "hourly":
        trigger = IntervalTrigger(hours=1)
        schedule_info = "hourly"
    elif recurring == "weekly" and day_of_week:
        if time:
            try:
                h, m = map(int, time.split(":"))
            except ValueError:
                raise ValueError("Time must be in HH:MM format")
        else:
            h, m = 9, 0
        trigger = CronTrigger(day_of_week=day_of_week[:3].lower(), hour=h, minute=m)
        schedule_info = f"weekly on {day_of_week}" + (f" at {time}" if time else "")
    elif datetime:
        trigger = DateTrigger(run_date=dt.fromisoformat(datetime))
        schedule_info = f"once at {datetime}"
    else:
        offset = timedelta(
            seconds=seconds or 0,
            minutes=minutes or 0,
            hours=hours or 0,
            days=days or 0,
        )

        if not offset:
            raise ValueError("Must specify when to send reminder")

        run_time = dt.now() + offset
        trigger = DateTrigger(run_date=run_time)

        parts = []
        if days:
            parts.append(f"{days} days")
        if hours:
            parts.append(f"{hours} hours")
        if minutes:
            parts.append(f"{minutes} minutes")
        if seconds:
            parts.append(f"{seconds} seconds")
        schedule_info = f"once (in {' '.join(parts)})"

    assert _context is not None
    _context.scheduler.add_job(
        func=send_reminder_job,
        trigger=trigger,
        args=[reminder_id, message],
        id=reminder_id,
        replace_existing=True,
    )

    next_run = _context.scheduler.get_job(reminder_id).next_run_time

    with closing(get_db()) as conn:
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
    return {
        "id": reminder_id,
        "message": message,
        "schedule": schedule_info,
        "next_run": next_run.isoformat() if next_run else None,
        "status": "scheduled",
    }


@mcp.tool()
def list_reminders() -> list[dict]:
    """List all active reminders"""
    assert _context is not None
    with closing(get_db()) as conn:
        cursor = conn.execute("SELECT * FROM reminders")
        reminder_data = {row["id"]: dict(row) for row in cursor}

    reminders = []
    for job in _context.scheduler.get_jobs():
        if job.id in reminder_data:
            reminders.append(
                {
                    "id": job.id,
                    "message": reminder_data[job.id]["message"],
                    "schedule": reminder_data[job.id]["schedule_type"],
                    "next_run": (job.next_run_time.isoformat() if job.next_run_time else None),
                    "status": "active" if job.next_run_time else "paused",
                }
            )
    return reminders


@mcp.tool()
def cancel_reminder(reminder_id: str) -> dict:
    assert _context is not None
    try:
        _context.scheduler.remove_job(reminder_id)
        with closing(get_db()) as conn:
            conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            conn.commit()
        return {"status": "cancelled", "id": reminder_id}
    except Exception as e:
        raise ValueError(f"Reminder {reminder_id} not found") from e


@mcp.tool()
def add_task(title: str, due: str | None = None, priority: int = 2, metadata: str | None = None) -> dict:
    """priority: 1 (low), 2 (normal), 3 (high). due: 'today', 'tomorrow', or YYYY-MM-DD"""
    if priority not in (1, 2, 3):
        raise ValueError("Priority must be 1 (low), 2 (normal), or 3 (high)")

    task_id = str(uuid.uuid4())[:8]
    due_date = parse_relative_date(due) if due else None

    with closing(get_db()) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, priority, due_date, metadata) VALUES (?, ?, ?, ?, ?)",
            (task_id, title, priority, due_date, metadata),
        )
        conn.commit()

    return {
        "id": task_id,
        "title": title,
        "status": "pending",
        "priority": priority,
        "due_date": due_date,
        "metadata": metadata,
    }


@mcp.tool()
def list_tasks(show_completed: bool = False) -> list[dict]:
    with closing(get_db()) as conn:
        query = "SELECT * FROM tasks"
        if not show_completed:
            query += " WHERE status != 'done'"
        query += " ORDER BY priority DESC, due_date ASC NULLS LAST, created_at DESC"

        cursor = conn.execute(query)
        tasks = [dict(row) for row in cursor]

    return tasks


@mcp.tool()
def update_task(id: str, status: str | None = None, title: str | None = None, metadata: str | None = None, priority: int | None = None) -> dict:
    """priority: 1 (low), 2 (normal), 3 (high). status: 'pending' or 'done'"""
    if status and status not in ("pending", "done"):
        raise ValueError("Status must be pending or done")
    if priority is not None and priority not in (1, 2, 3):
        raise ValueError("Priority must be 1 (low), 2 (normal), or 3 (high)")

    with closing(get_db()) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (id,))
        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Task {id} not found")

        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status == "done":
                updates.append("completed_at = ?")
                params.append(dt.now().isoformat())
            elif status == "pending":
                updates.append("completed_at = NULL")

        if title is not None:
            updates.append("title = ?")
            params.append(title)

        if metadata is not None:
            updates.append("metadata = ?")
            params.append(metadata)

        if priority is not None:
            updates.append("priority = ?")
            params.append(priority)

        if updates:
            params.append(id)
            query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)
            conn.commit()

        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (id,))
        task = dict(cursor.fetchone())

    return task
