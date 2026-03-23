"""Minimal task log for Phase 4 — shadow record of work units.

A task is created for each qualifying novel notification as it enters the
processing queue.  It does not control execution — Claude still runs exactly
as before.  The purpose is to validate whether event classes map cleanly to
comprehensible task categories.

Task types and their expected outputs:
    user_request     — direct WhatsApp/LinkedIn message from the user
    email_action     — actionable email (non-newsletter)
    reminder_action  — reminder from the reminder daemon
    calendar_alert   — calendar event notification
    linkedin_message — direct LinkedIn message

Status lifecycle (Phase 4):
    open   — task created, processing queued
    closed — processing attempt completed (optimistic; does not imply success)

Never raises — task failures must never affect the main execution path.
"""

import datetime as dt
import pathlib as pl
import sqlite3
import typing as tp
import uuid

if tp.TYPE_CHECKING:
    import vesta.models as vm

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id          TEXT    NOT NULL UNIQUE,
    event_id         TEXT    NOT NULL,
    task_type        TEXT    NOT NULL,
    created_at       TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'open',
    expected_outputs TEXT,
    closed_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_event_id ON tasks (event_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_created  ON tasks (created_at);
"""

# Maps (source, notification_type) → (task_type, expected_outputs)
_CLASSIFIERS: dict[tuple[str, str], tuple[str, str]] = {
    ("whatsapp", "message"): ("user_request", "reply via whatsapp"),
    ("linkedin", "message"): ("linkedin_message", "reply via linkedin"),
    ("microsoft", "email"): ("email_action", "email reply or flag"),
    ("reminder", "reminder"): ("reminder_action", "act on reminder"),
    ("microsoft", "calendar"): ("calendar_alert", "acknowledge and prepare"),
}


def _open(db_path: pl.Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def classify(notif: "vm.Notification") -> "tuple[str, str] | None":
    """Return (task_type, expected_outputs) for a notification, or None if not qualifying."""
    return _CLASSIFIERS.get((notif.source, notif.type))


def open_tasks(
    notifications: "list[vm.Notification]",
    *,
    db_path: pl.Path,
    invocation_id: str | None,
) -> list[str]:
    """Create open task records for qualifying notifications.

    Returns the list of created task_ids so the caller can close them later.
    Returns [] on any error (fail open — never blocks processing).
    """
    qualifying = [(n, classify(n)) for n in notifications if classify(n) is not None]
    if not qualifying:
        return []
    try:
        from vesta.core.ledger import _derive_event_id  # noqa: PLC0415

        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        task_ids: list[str] = []
        for notif, (task_type, expected_outputs) in qualifying:
            tid = str(uuid.uuid4())
            eid = _derive_event_id(notif)
            conn.execute(
                "INSERT INTO tasks (task_id, event_id, task_type, created_at, status, expected_outputs) VALUES (?, ?, ?, ?, 'open', ?)",
                (tid, eid, task_type, now, expected_outputs),
            )
            task_ids.append(tid)
        conn.commit()
        conn.close()
        return task_ids
    except Exception:
        return []


def close_tasks(task_ids: list[str], *, db_path: pl.Path) -> None:
    """Mark a list of tasks as closed (optimistic — does not imply success).

    Never raises.
    """
    if not task_ids:
        return
    try:
        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        placeholders = ",".join("?" * len(task_ids))
        conn.execute(
            f"UPDATE tasks SET status = 'closed', closed_at = ? WHERE task_id IN ({placeholders})",
            [now, *task_ids],
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def query_recent(
    db_path: pl.Path,
    *,
    limit: int = 20,
    status: "str | None" = None,
) -> "list[dict[str, object]]":
    """Return recent tasks, newest first.  Optionally filter by status."""
    try:
        conn = _open(db_path)
        if status:
            rows = conn.execute(
                "SELECT task_id, event_id, task_type, created_at, status, expected_outputs, closed_at "
                "FROM tasks WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT task_id, event_id, task_type, created_at, status, expected_outputs, closed_at FROM tasks ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        keys = ("task_id", "event_id", "task_type", "created_at", "status", "expected_outputs", "closed_at")
        return [dict(zip(keys, row)) for row in rows]
    except Exception:
        return []


def task_stats(db_path: pl.Path) -> "dict[str, int]":
    """Return total, open, and closed task counts."""
    try:
        conn = _open(db_path)
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        open_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE status = 'open'").fetchone()[0]
        conn.close()
        return {"total": total, "open": open_count, "closed": total - open_count}
    except Exception:
        return {"total": 0, "open": 0, "closed": 0}
