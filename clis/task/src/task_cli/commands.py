from datetime import datetime as dt, timedelta, UTC
from contextlib import closing
from pathlib import Path
import uuid

from .config import Config
from . import db


def normalize_priority(priority: int | str) -> int:
    """Convert priority string to int. Accepts 1/2/3 or 'low'/'normal'/'high'."""
    if isinstance(priority, int):
        if priority not in (1, 2, 3):
            raise ValueError(f"Priority must be 1-3 or 'low'/'normal'/'high', got {priority}")
        return priority

    # Handle string that might be a digit
    if isinstance(priority, str) and priority.isdigit():
        return normalize_priority(int(priority))

    priority_map = {"low": 1, "normal": 2, "high": 3}
    normalized = priority_map.get(priority.lower())
    if normalized is None:
        raise ValueError(f"Priority must be 1-3 or 'low'/'normal'/'high', got '{priority}'")
    return normalized


def _to_utc(datetime_str: str, timezone_str: str) -> str:
    """Convert datetime string with timezone to UTC ISO-8601 string."""
    from zoneinfo import ZoneInfo

    naive_dt = dt.fromisoformat(datetime_str.replace("Z", "+00:00"))

    if naive_dt.tzinfo is not None:
        return naive_dt.astimezone(UTC).isoformat()

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

    if due_datetime is not None:
        if timezone_str is None:
            raise ValueError("timezone is required when due_datetime is provided")
        return _to_utc(due_datetime, timezone_str)

    offset = timedelta(
        minutes=due_in_minutes or 0,
        hours=due_in_hours or 0,
        days=due_in_days or 0,
    )
    if offset.total_seconds() > 0:
        return (dt.now(UTC) + offset).isoformat()

    return None


def _get_metadata_path(data_dir: Path, task_id: str) -> Path:
    return data_dir / "metadata" / f"{task_id}.md"


def _read_metadata(data_dir: Path, task_id: str) -> str | None:
    path = _get_metadata_path(data_dir, task_id)
    if path.exists():
        try:
            return path.read_text()
        except OSError:
            return None
    return None


def _write_metadata(data_dir: Path, task_id: str, content: str):
    metadata_dir = data_dir / "metadata"
    metadata_dir.mkdir(exist_ok=True)
    _get_metadata_path(data_dir, task_id).write_text(content)


def _delete_metadata(data_dir: Path, task_id: str):
    path = _get_metadata_path(data_dir, task_id)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def _task_with_metadata(data_dir: Path, row: dict, include_content: bool = False) -> dict:
    task = dict(row)
    task_id = task["id"]
    task["metadata_path"] = str(_get_metadata_path(data_dir, task_id))
    if include_content:
        task["metadata_content"] = _read_metadata(data_dir, task_id)
    return task


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
        tasks = [_task_with_metadata(config.data_dir, dict(row), include_content=False) for row in cursor]

    return tasks


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
        tasks = [_task_with_metadata(config.data_dir, dict(row), include_content=False) for row in cursor]
    return tasks
