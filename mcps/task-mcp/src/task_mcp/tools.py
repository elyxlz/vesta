from datetime import datetime as dt, timedelta
from contextlib import closing, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
import argparse
import sqlite3
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context


def _validate_directory(path_str: str | None, param_name: str) -> Path:
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
class TaskContext:
    data_dir: Path
    log_dir: Path


@asynccontextmanager
async def task_lifespan(server: FastMCP) -> AsyncIterator[TaskContext]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    parser.add_argument("--log-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    data_dir = _validate_directory(args.data_dir, "data-dir")
    log_dir = _validate_directory(args.log_dir, "log-dir")

    ctx = TaskContext(data_dir, log_dir)
    init_db(ctx)

    try:
        yield ctx
    finally:
        pass


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
                completed_at TEXT
            )
        """)
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
            return (now + timedelta(days=int(date_str[3:-5]))).date().isoformat()
        except ValueError:
            pass

    return date_str


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
def add_task(ctx: Context, title: str, due: str | None = None, priority: int | str = 2, metadata: str | None = None) -> dict:
    """priority: 1-3 or 'low'/'normal'/'high'. due: 'today', 'tomorrow', or YYYY-MM-DD"""
    context: TaskContext = ctx.request_context.lifespan_context
    priority = normalize_priority(priority)

    task_id = str(uuid.uuid4())[:8]
    due_date = parse_relative_date(due) if due else None

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
