from datetime import datetime as dt, timedelta
from contextlib import closing, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
import argparse
import logging
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context

from . import monitor


def _validate_directory(path_str: str | None, *, param_name: str, required: bool = True) -> Path | None:
    if not path_str:
        if required:
            raise ValueError(f"Error: --{param_name} is required")
        return None

    path = Path(path_str).resolve()
    path.mkdir(parents=True, exist_ok=True)

    test_file = path / ".write_test"
    try:
        test_file.touch()
        test_file.unlink()
    except Exception as e:
        raise RuntimeError(f"Error: --{param_name} directory is not writable: {path} ({e})")

    return path


def _setup_logger(log_dir: Path) -> logging.Logger:
    logger = logging.getLogger("task-mcp-monitor")
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_dir / "monitor.log")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(handler)
    return logger


@dataclass
class TaskContext:
    data_dir: Path
    log_dir: Path
    notif_dir: Path | None
    monitor_stop_event: threading.Event | None
    monitor_thread: threading.Thread | None


@asynccontextmanager
async def task_lifespan(server: FastMCP) -> AsyncIterator[TaskContext]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--log-dir", type=str, required=True)
    parser.add_argument("--notifications-dir", type=str, required=False)
    parser.add_argument("--monitor-interval", type=int, default=60)
    args, _ = parser.parse_known_args()

    data_dir = _validate_directory(args.data_dir, param_name="data-dir")
    assert data_dir is not None
    log_dir = _validate_directory(args.log_dir, param_name="log-dir")
    assert log_dir is not None
    notif_dir = _validate_directory(args.notifications_dir, param_name="notifications-dir", required=False)

    monitor_stop_event = None
    monitor_thread = None

    if notif_dir:
        monitor_stop_event = threading.Event()
        logger = _setup_logger(log_dir)
        monitor_thread = threading.Thread(
            target=monitor.run,
            args=(data_dir / "tasks.db", notif_dir, monitor_stop_event, logger, args.monitor_interval),
            daemon=True,
        )

    ctx = TaskContext(data_dir, log_dir, notif_dir, monitor_stop_event, monitor_thread)
    init_db(ctx)

    if monitor_thread:
        monitor_thread.start()

    try:
        yield ctx
    finally:
        if monitor_stop_event:
            monitor_stop_event.set()
        if monitor_thread:
            monitor_thread.join(timeout=5)


mcp = FastMCP("task-mcp", lifespan=task_lifespan)


def get_db(ctx: TaskContext):
    conn = sqlite3.connect(ctx.data_dir / "tasks.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(ctx: TaskContext):
    with closing(get_db(ctx)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                notified_thresholds TEXT
            )
        """)
        # Add column if it doesn't exist (for existing databases)
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN notified_thresholds TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()


def parse_due_datetime(date_str: str) -> str | None:
    """Parse due date/time. Supports:
    - 'today', 'today 3pm', 'today 15:00'
    - 'tomorrow', 'tomorrow 9am'
    - 'in N days'
    - 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM'
    If no time specified, defaults to 09:00 local time.
    Returns ISO datetime string.
    """
    if not date_str:
        return None

    date_str = date_str.strip()
    now = dt.now()

    # Check if it's already a full ISO datetime (YYYY-MM-DDTHH:MM) - return as-is
    if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", date_str):
        return date_str

    # Extract time if present (e.g., "today 3pm", "tomorrow 15:00")
    time_match = re.search(r"(\d{1,2})(?::(\d{2}))?(?:\s*)?(am|pm)?$", date_str, re.IGNORECASE)
    hour, minute = 9, 0  # default to 9am

    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        am_pm = time_match.group(3)
        if am_pm:
            if am_pm.lower() == "pm" and hour < 12:
                hour += 12
            elif am_pm.lower() == "am" and hour == 12:
                hour = 0
        date_str = date_str[: time_match.start()].strip()

    date_lower = date_str.lower()

    if date_lower == "today" or date_lower == "":
        base_date = now.date()
    elif date_lower == "tomorrow":
        base_date = (now + timedelta(days=1)).date()
    elif date_lower.startswith("in ") and "day" in date_lower:
        days_match = re.search(r"in\s+(\d+)\s+days?", date_lower)
        if days_match:
            base_date = (now + timedelta(days=int(days_match.group(1)))).date()
        else:
            return date_str
    elif re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        # ISO date without time - add default time
        base_date = dt.fromisoformat(date_str).date()
    else:
        return date_str  # Return as-is if unparseable

    return dt(base_date.year, base_date.month, base_date.day, hour, minute).isoformat()


def normalize_priority(priority: int | str) -> int:
    """Convert priority string to int. Accepts 1/2/3 or 'low'/'normal'/'high'."""
    if isinstance(priority, int):
        if priority not in (1, 2, 3):
            raise ValueError(f"Priority must be 1-3 or 'low'/'normal'/'high', got {priority}")
        return priority

    priority_map = {"low": 1, "normal": 2, "high": 3}
    normalized = priority_map.get(priority.lower())
    if normalized is None:
        raise ValueError(f"Priority must be 1-3 or 'low'/'normal'/'high', got '{priority}'")
    return normalized


@mcp.tool()
def add_task(ctx: Context, *, title: str, due: str | None = None, priority: int | str = 2, metadata: str | None = None) -> dict:
    """priority: 1-3 or 'low'/'normal'/'high'. due: 'today', 'today 3pm', 'tomorrow 9am', 'in 3 days', 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM'. Defaults to 9am if no time given."""
    context: TaskContext = ctx.request_context.lifespan_context
    priority = normalize_priority(priority)

    task_id = str(uuid.uuid4())[:8]
    due_date = parse_due_datetime(due) if due else None

    with closing(get_db(context)) as conn:
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
def list_tasks(ctx: Context, show_completed: bool = False) -> list[dict]:
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        query = "SELECT * FROM tasks"
        if not show_completed:
            query += " WHERE status != 'done'"
        query += " ORDER BY priority DESC, due_date ASC NULLS LAST, created_at DESC"

        cursor = conn.execute(query)
        tasks = [dict(row) for row in cursor]

    return tasks


@mcp.tool()
def update_task(
    ctx: Context,
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    metadata: str | None = None,
    priority: int | str | None = None,
    append_metadata: bool = True,
) -> dict:
    """priority: 1-3 or 'low'/'normal'/'high'. status: 'pending' or 'done'. append_metadata: if True (default), appends to existing metadata; if False, replaces it"""
    context: TaskContext = ctx.request_context.lifespan_context
    if status and status not in ("pending", "done"):
        raise ValueError(f"Status must be pending or done, got {status}")
    if priority is not None:
        priority = normalize_priority(priority)

    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Task '{task_id}' not found. Use list_tasks() to see available tasks.")

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

        final_metadata = metadata
        if metadata is not None and append_metadata:
            current_metadata = result["metadata"]
            if current_metadata:
                final_metadata = f"{current_metadata}\n{metadata}"

        for field, value in [("title", title), ("metadata", final_metadata), ("priority", priority)]:
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if updates:
            params.append(task_id)
            query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)
            conn.commit()

        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = dict(cursor.fetchone())

    return task


@mcp.tool()
def get_task(ctx: Context, task_id: str) -> dict:
    """Get a single task by ID"""
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Task '{task_id}' not found. Use list_tasks() to see available tasks.")
        return dict(result)


@mcp.tool()
def delete_task(ctx: Context, task_id: str) -> dict:
    """Delete a task permanently"""
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not cursor.fetchone():
            raise ValueError(f"Task '{task_id}' not found. Use list_tasks() to see available tasks.")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    return {"status": "deleted", "task_id": task_id}


@mcp.tool()
def search_tasks(ctx: Context, query: str, show_completed: bool = False) -> list[dict]:
    """Search tasks by title. Returns tasks matching the query string."""
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        sql = "SELECT * FROM tasks WHERE title LIKE ?"
        if not show_completed:
            sql += " AND status != 'done'"
        sql += " ORDER BY priority DESC, due_date ASC NULLS LAST, created_at DESC"

        cursor = conn.execute(sql, (f"%{query}%",))
        tasks = [dict(row) for row in cursor]
    return tasks
