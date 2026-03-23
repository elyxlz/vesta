"""Minimal task log — Phase 4 + Phase 5.

Phase 4 introduced shadow task records for qualifying event classes.

Phase 5 binds invocations to task IDs for selected workflows and introduces
a richer lifecycle:

    queued    — task created, work item recognized, waiting in queue
    running   — Claude is actively processing; invocation_id written here
    completed — processing finished successfully
    failed    — processing failed or session was abandoned (watchdog)

Phase 5 also introduces work_item_id: a stable native identifier that allows
repeated events for the same logical work item to resolve to one task rather
than spawning a new one each time.  Pilot binding workflow: reminders
(work_item_id = reminder_id from the daemon).

For binding workflows, open_tasks() injects a brief task context string into
the prompt so Claude knows which task it is serving.

Task types and their expected outputs:
    user_request     — direct WhatsApp/LinkedIn message or console input
    email_action     — actionable email (non-newsletter)
    reminder_action  — reminder from the reminder daemon  ← binding pilot
    calendar_alert   — calendar event notification
    linkedin_message — direct LinkedIn message

Fail-open everywhere: task failures must never affect the main execution path.
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
    status           TEXT    NOT NULL DEFAULT 'queued',
    expected_outputs TEXT,
    invocation_id    TEXT,
    work_item_id     TEXT,
    started_at       TEXT,
    closed_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_tasks_event_id    ON tasks (event_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status      ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_created     ON tasks (created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_work_item   ON tasks (work_item_id);
"""

# Maps (source, notification_type) → (task_type, expected_outputs)
_CLASSIFIERS: dict[tuple[str, str], tuple[str, str]] = {
    ("whatsapp", "message"): ("user_request", "reply via whatsapp"),
    ("linkedin", "message"): ("linkedin_message", "reply via linkedin"),
    ("microsoft", "email"): ("email_action", "email reply or flag"),
    ("reminder", "reminder"): ("reminder_action", "act on reminder"),
    ("microsoft", "calendar"): ("calendar_alert", "acknowledge and prepare"),
}


def _extract_reminder_work_item(notif: "vm.Notification") -> "str | None":
    rid = notif.model_dump().get("reminder_id")
    return str(rid) if rid is not None else None


# Binding workflows: (source, type) → extractor that returns a stable work_item_id
_BINDING_EXTRACTORS: dict[tuple[str, str], tp.Callable[["vm.Notification"], "str | None"]] = {
    ("reminder", "reminder"): _extract_reminder_work_item,
}


def extract_work_item_id(notif: "vm.Notification") -> "str | None":
    """Return the stable work_item_id for binding workflows, or None if not applicable."""
    extractor = _BINDING_EXTRACTORS.get((notif.source, notif.type))
    if extractor is None:
        return None
    try:
        return extractor(notif)
    except Exception:
        return None


def _open(db_path: pl.Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add Phase 5 columns to existing databases (safe to run multiple times)."""
    new_cols = [
        ("invocation_id", "TEXT"),
        ("work_item_id", "TEXT"),
        ("started_at", "TEXT"),
    ]
    for col, defn in new_cols:
        try:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {defn}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # Column already exists


def classify(notif: "vm.Notification") -> "tuple[str, str] | None":
    """Return (task_type, expected_outputs) for a notification, or None if not qualifying."""
    return _CLASSIFIERS.get((notif.source, notif.type))


def _find_active_task_by_work_item(work_item_id: str, *, conn: sqlite3.Connection) -> "str | None":
    """Return the task_id of an active (non-terminal) task with the given work_item_id."""
    row = conn.execute(
        "SELECT task_id FROM tasks WHERE work_item_id = ? AND status NOT IN ('completed', 'failed') ORDER BY id DESC LIMIT 1",
        (work_item_id,),
    ).fetchone()
    return row[0] if row else None


def open_tasks(
    notifications: "list[vm.Notification]",
    *,
    db_path: pl.Path,
    invocation_id: str | None,
) -> "tuple[list[str], str]":
    """Create queued task records for qualifying notifications.

    Returns (task_ids, prompt_context):
    - task_ids: list of task_ids (created or found via work_item binding)
    - prompt_context: task context string to append to the prompt for binding
      workflows; empty string if no binding workflows in this batch.

    For binding workflows, looks up any active task with the same work_item_id
    before creating a new one — so repeated events for the same work item
    resolve to one task.

    Returns ([], "") on any error (fail open — never blocks processing).
    """
    qualifying: list[tuple[vm.Notification, tuple[str, str]]] = []
    for n in notifications:
        c = classify(n)
        if c is not None:
            qualifying.append((n, c))
    if not qualifying:
        return [], ""
    try:
        from vesta.core.ledger import _derive_event_id  # noqa: PLC0415

        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        task_ids: list[str] = []
        context_lines: list[str] = []

        for notif, (task_type, expected_outputs) in qualifying:
            eid = _derive_event_id(notif)
            # extract_work_item_id() swallows its own exceptions and returns None on
            # failure, so wid=None is always a safe fallback — the task is created in
            # "unbound mode" (no work_item_id, no context injection) and proceeds
            # through the normal lifecycle without any binding semantics.
            wid = extract_work_item_id(notif)

            # Phase 3 (ledger) suppresses exact-duplicate event_ids before we reach
            # here, so a suppressed event never participates in task creation or
            # binding.  The only way a duplicate work_item_id can appear in this loop
            # is if two *different* event_ids share the same underlying work item (e.g.
            # a snoozed reminder firing again).  In that case we reuse the existing
            # active task rather than creating a second one.
            if wid is not None:
                existing_tid = _find_active_task_by_work_item(wid, conn=conn)
                if existing_tid:
                    task_ids.append(existing_tid)
                    context_lines.append(
                        f"[Task: id={existing_tid}, type={task_type}, work_item_id={wid}]"
                    )
                    continue

            tid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO tasks (task_id, event_id, task_type, created_at, status, expected_outputs, work_item_id) "
                "VALUES (?, ?, ?, ?, 'queued', ?, ?)",
                (tid, eid, task_type, now, expected_outputs, wid),
            )
            task_ids.append(tid)
            if wid is not None:
                # Only binding workflows (wid is not None) get context injected into
                # the prompt.  Unbound tasks are tracked silently.
                context_lines.append(
                    f"[Task: id={tid}, type={task_type}, work_item_id={wid}]"
                )

        conn.commit()
        conn.close()
        prompt_context = "\n".join(context_lines)
        return task_ids, prompt_context
    except Exception:
        # Fail open: on any DB or logic error, return empty task_ids and no context.
        # The caller (process_batch) will queue the prompt with an empty task_ids list,
        # meaning the notification is processed in pure legacy mode with no task
        # lifecycle management and no side effects on any existing task state.
        return [], ""


def set_running(task_ids: list[str], *, invocation_id: str | None, db_path: pl.Path) -> None:
    """Transition tasks to running state, recording the invocation_id.

    Called when Claude actually begins processing — not at queue time.
    Never raises.
    """
    if not task_ids:
        return
    try:
        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        placeholders = ",".join("?" * len(task_ids))
        conn.execute(
            f"UPDATE tasks SET status = 'running', invocation_id = ?, started_at = ? "
            f"WHERE task_id IN ({placeholders}) AND status = 'queued'",
            [invocation_id, now, *task_ids],
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def set_completed(task_ids: list[str], *, db_path: pl.Path) -> None:
    """Transition tasks to completed state.  Never raises."""
    if not task_ids:
        return
    try:
        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        placeholders = ",".join("?" * len(task_ids))
        conn.execute(
            f"UPDATE tasks SET status = 'completed', closed_at = ? WHERE task_id IN ({placeholders})",
            [now, *task_ids],
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def set_failed(task_ids: list[str], *, db_path: pl.Path) -> None:
    """Transition tasks to failed state.  Never raises."""
    if not task_ids:
        return
    try:
        conn = _open(db_path)
        now = dt.datetime.now().isoformat()
        placeholders = ",".join("?" * len(task_ids))
        conn.execute(
            f"UPDATE tasks SET status = 'failed', closed_at = ? WHERE task_id IN ({placeholders})",
            [now, *task_ids],
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def mark_abandoned(timeout_seconds: float, *, db_path: pl.Path) -> int:
    """Mark tasks stuck in running state as failed (watchdog).

    A task is considered abandoned if it has been in running state for longer
    than timeout_seconds without completing.  Returns the number of tasks
    reclassified.  Never raises.
    """
    try:
        conn = _open(db_path)
        cutoff = (dt.datetime.now() - dt.timedelta(seconds=timeout_seconds)).isoformat()
        result = conn.execute(
            "UPDATE tasks SET status = 'failed', closed_at = ? "
            "WHERE status = 'running' AND started_at < ?",
            (dt.datetime.now().isoformat(), cutoff),
        )
        count = result.rowcount
        conn.commit()
        conn.close()
        return count
    except Exception:
        return 0


def close_tasks(task_ids: list[str], *, db_path: pl.Path) -> None:
    """Backward-compatible close — maps to set_completed.

    Kept so Phase 4 callers continue to work unchanged.  Never raises.
    """
    set_completed(task_ids, db_path=db_path)


def query_recent(
    db_path: pl.Path,
    *,
    limit: int = 20,
    status: "str | None" = None,
) -> "list[dict[str, object]]":
    """Return recent tasks, newest first.  Optionally filter by status."""
    try:
        conn = _open(db_path)
        cols = "task_id, event_id, task_type, created_at, status, expected_outputs, invocation_id, work_item_id, started_at, closed_at"
        if status:
            rows = conn.execute(
                f"SELECT {cols} FROM tasks WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {cols} FROM tasks ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        conn.close()
        keys = ("task_id", "event_id", "task_type", "created_at", "status", "expected_outputs", "invocation_id", "work_item_id", "started_at", "closed_at")
        return [dict(zip(keys, row)) for row in rows]
    except Exception:
        return []


def open_console_task(msg: str, *, db_path: pl.Path, invocation_id: str | None) -> "str | None":
    """Create a queued user_request task for a direct console message.

    Returns the task_id so the caller can drive its lifecycle, or None on error.
    """
    import hashlib  # noqa: PLC0415

    try:
        conn = _open(db_path)
        tid = str(uuid.uuid4())
        eid = "console:" + hashlib.sha256(msg.encode()).hexdigest()[:16]
        now = dt.datetime.now().isoformat()
        conn.execute(
            "INSERT INTO tasks (task_id, event_id, task_type, created_at, status, expected_outputs) "
            "VALUES (?, ?, 'user_request', ?, 'queued', 'reply via console')",
            (tid, eid, now),
        )
        conn.commit()
        conn.close()
        return tid
    except Exception:
        return None


def task_stats(db_path: pl.Path) -> "dict[str, int]":
    """Return task counts by status."""
    try:
        conn = _open(db_path)
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        by_status: dict[str, int] = {}
        for row in conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall():
            by_status[row[0]] = row[1]
        conn.close()
        return {
            "total": total,
            "queued": by_status.get("queued", 0),
            "running": by_status.get("running", 0),
            "completed": by_status.get("completed", 0),
            "failed": by_status.get("failed", 0),
            # legacy statuses from Phase 4 DBs
            "open": by_status.get("open", 0),
            "closed": by_status.get("closed", 0),
        }
    except Exception:
        return {"total": 0, "queued": 0, "running": 0, "completed": 0, "failed": 0, "open": 0, "closed": 0}
