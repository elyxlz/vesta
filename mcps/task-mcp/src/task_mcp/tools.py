from datetime import datetime as dt, timedelta, UTC
from contextlib import closing, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
from typing import TypedDict
import argparse
import logging
import sqlite3
import threading
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context

from . import monitor


class Task(TypedDict, total=False):
    id: str
    title: str
    status: str
    priority: int
    due_date: str | None
    metadata_path: str | None
    metadata_content: str | None
    created_at: str
    completed_at: str | None
    notified_thresholds: str | None


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


def _migrate_metadata_to_files(ctx: TaskContext, conn: sqlite3.Connection):
    """Migrate metadata from database TEXT column to individual files."""
    metadata_dir = ctx.data_dir / "metadata"
    metadata_dir.mkdir(exist_ok=True)

    # Check if metadata column exists
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor]
    if "metadata" not in columns:
        return

    # Migrate existing metadata to files
    cursor = conn.execute("SELECT id, metadata FROM tasks WHERE metadata IS NOT NULL")
    for row in cursor:
        task_id, metadata = row
        if metadata:
            (metadata_dir / f"{task_id}.md").write_text(metadata)

    # Recreate table without metadata column (SQLite doesn't support DROP COLUMN)
    conn.execute("""
        CREATE TABLE tasks_new (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
            priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
            due_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            notified_thresholds TEXT
        )
    """)
    conn.execute("""
        INSERT INTO tasks_new (id, title, status, priority, due_date, created_at, completed_at, notified_thresholds)
        SELECT id, title, status, priority, due_date, created_at, completed_at, notified_thresholds FROM tasks
    """)
    conn.execute("DROP TABLE tasks")
    conn.execute("ALTER TABLE tasks_new RENAME TO tasks")


def init_db(ctx: TaskContext):
    with closing(get_db(ctx)) as conn:
        # Schema versioning
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        cursor = conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        if not row:
            conn.execute("INSERT INTO schema_version (version) VALUES (0)")
            version = 0
        else:
            version = row[0]

        # Create tasks table (new schema without metadata column)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                notified_thresholds TEXT
            )
        """)

        # Migration v0 -> v1: Move metadata to files
        if version < 1:
            _migrate_metadata_to_files(ctx, conn)
            conn.execute("UPDATE schema_version SET version = 1")

        conn.commit()


def _to_utc(datetime_str: str, timezone_str: str) -> str:
    """Convert datetime string with timezone to UTC ISO-8601 string."""
    from zoneinfo import ZoneInfo

    # Parse the datetime
    naive_dt = dt.fromisoformat(datetime_str.replace("Z", "+00:00"))

    # If already has timezone info, convert to UTC
    if naive_dt.tzinfo is not None:
        return naive_dt.astimezone(UTC).isoformat()

    # Apply the provided timezone and convert to UTC
    local_tz = ZoneInfo(timezone_str)
    local_dt = naive_dt.replace(tzinfo=local_tz)
    return local_dt.astimezone(UTC).isoformat()


def _compute_due_date(
    due_datetime: str | None,
    timezone_str: str | None,
    due_in_minutes: int | None,
    due_in_hours: int | None,
    due_in_days: int | None,
) -> str | None:
    """Compute due date from various input modes. Returns UTC ISO-8601 string."""

    # Mode 1: Absolute datetime with timezone
    if due_datetime is not None:
        if timezone_str is None:
            raise ValueError("timezone is required when due_datetime is provided")
        return _to_utc(due_datetime, timezone_str)

    # Mode 2: Relative offset
    offset = timedelta(
        minutes=due_in_minutes or 0,
        hours=due_in_hours or 0,
        days=due_in_days or 0,
    )
    if offset.total_seconds() > 0:
        return (dt.now(UTC) + offset).isoformat()

    return None


def _get_metadata_path(ctx: TaskContext, task_id: str) -> Path:
    return ctx.data_dir / "metadata" / f"{task_id}.md"


def _read_metadata(ctx: TaskContext, task_id: str) -> str | None:
    path = _get_metadata_path(ctx, task_id)
    if path.exists():
        try:
            return path.read_text()
        except OSError:
            return None
    return None


def _write_metadata(ctx: TaskContext, task_id: str, content: str):
    metadata_dir = ctx.data_dir / "metadata"
    metadata_dir.mkdir(exist_ok=True)
    _get_metadata_path(ctx, task_id).write_text(content)


def _delete_metadata(ctx: TaskContext, task_id: str):
    path = _get_metadata_path(ctx, task_id)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _task_with_metadata(ctx: TaskContext, row: dict, include_content: bool = False) -> dict:
    task = dict(row)
    task_id = task["id"]
    task["metadata_path"] = str(_get_metadata_path(ctx, task_id))
    if include_content:
        task["metadata_content"] = _read_metadata(ctx, task_id)
    return task


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
def add_task(
    ctx: Context,
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
    """due_datetime: ISO-8601 (requires timezone). due_in_*: relative offset from now (UTC). priority: 1-3 or 'low'/'normal'/'high'. Returns metadata_path for file-based metadata editing."""
    context: TaskContext = ctx.request_context.lifespan_context
    priority = normalize_priority(priority)

    task_id = str(uuid.uuid4())[:8]
    due_date = _compute_due_date(due_datetime, timezone, due_in_minutes, due_in_hours, due_in_days)

    with closing(get_db(context)) as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, priority, due_date) VALUES (?, ?, ?, ?)",
            (task_id, title, priority, due_date),
        )
        conn.commit()

    if initial_metadata:
        _write_metadata(context, task_id, initial_metadata)

    return {
        "id": task_id,
        "title": title,
        "status": "pending",
        "priority": priority,
        "due_date": due_date,
        "metadata_path": str(_get_metadata_path(context, task_id)),
    }


@mcp.tool()
def list_tasks(ctx: Context, *, show_completed: bool = False) -> list[dict]:
    """Returns metadata_path for each task (use get_task or Read tool for content)."""
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        query = "SELECT * FROM tasks"
        if not show_completed:
            query += " WHERE status != 'done'"
        query += " ORDER BY priority DESC, due_date ASC NULLS LAST, created_at DESC"

        cursor = conn.execute(query)
        tasks = [_task_with_metadata(context, dict(row), include_content=False) for row in cursor]

    return tasks


@mcp.tool()
def update_task(
    ctx: Context,
    *,
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    priority: int | str | None = None,
) -> dict:
    """priority: 1-3 or 'low'/'normal'/'high'. status: 'pending' or 'done'. Use Read/Edit tools on metadata_path for metadata."""
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
        return _task_with_metadata(context, dict(cursor.fetchone()), include_content=True)


@mcp.tool()
def get_task(ctx: Context, *, task_id: str) -> dict:
    """Get a single task by ID with full metadata content."""
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        result = cursor.fetchone()
        if not result:
            raise ValueError(f"Task '{task_id}' not found. Use list_tasks() to see available tasks.")
        return _task_with_metadata(context, dict(result), include_content=True)


@mcp.tool()
def delete_task(ctx: Context, *, task_id: str) -> dict:
    """Delete a task permanently, including its metadata file."""
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        if not cursor.fetchone():
            raise ValueError(f"Task '{task_id}' not found. Use list_tasks() to see available tasks.")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    _delete_metadata(context, task_id)
    return {"status": "deleted", "task_id": task_id}


@mcp.tool()
def search_tasks(ctx: Context, *, query: str, show_completed: bool = False) -> list[dict]:
    """Search tasks by title. Returns metadata_path for each task."""
    context: TaskContext = ctx.request_context.lifespan_context
    with closing(get_db(context)) as conn:
        sql = "SELECT * FROM tasks WHERE title LIKE ?"
        if not show_completed:
            sql += " AND status != 'done'"
        sql += " ORDER BY priority DESC, due_date ASC NULLS LAST, created_at DESC"

        cursor = conn.execute(sql, (f"%{query}%",))
        tasks = [_task_with_metadata(context, dict(row), include_content=False) for row in cursor]
    return tasks
