from datetime import datetime as dt, timedelta
from contextlib import closing, asynccontextmanager
from dataclasses import dataclass
from collections.abc import AsyncIterator
import argparse
import sqlite3
import uuid
from pathlib import Path
from mcp.server.fastmcp import FastMCP, Context


@dataclass
class TaskContext:
    data_dir: Path


@asynccontextmanager
async def task_lifespan(server: FastMCP) -> AsyncIterator[TaskContext]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=str, required=True)
    args, _ = parser.parse_known_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    ctx = TaskContext(data_dir)
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
            days = int(date_str[3:-5])
            return (now + timedelta(days=days)).date().isoformat()
        except ValueError:
            pass

    return date_str


@mcp.tool()
def add_task(ctx: Context, title: str, due: str | None = None, priority: int = 2, metadata: str | None = None) -> dict:
    """priority: 1 (low), 2 (normal), 3 (high). due: 'today', 'tomorrow', or YYYY-MM-DD"""
    context: TaskContext = ctx.request_context.lifespan_context
    if priority not in (1, 2, 3):
        raise ValueError(f"Priority must be 1 (low), 2 (normal), or 3 (high), got {priority}")

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
def update_task(ctx: Context, id: str, status: str | None = None, title: str | None = None, metadata: str | None = None, priority: int | None = None) -> dict:
    """priority: 1 (low), 2 (normal), 3 (high). status: 'pending' or 'done'"""
    context: TaskContext = ctx.request_context.lifespan_context
    if status and status not in ("pending", "done"):
        raise ValueError(f"Status must be pending or done, got {status}")
    if priority is not None and priority not in (1, 2, 3):
        raise ValueError(f"Priority must be 1 (low), 2 (normal), or 3 (high), got {priority}")

    with closing(get_db(context)) as conn:
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
