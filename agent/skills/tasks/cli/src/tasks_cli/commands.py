import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel

from . import db
from .config import Config
from .format import PRIORITY_LABEL, rel_delta
from .scheduler import write_notification

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class DueSpec(BaseModel):
    """A task due date: an absolute datetime + timezone, or a relative due-in offset.

    The due-setting fields only move the date. `clear` is the one that unsets it, and cannot be
    combined with a due-setting field.
    """

    due_datetime: str | None = None
    timezone: str | None = None
    due_in_minutes: int | None = None
    due_in_hours: int | None = None
    due_in_days: int | None = None
    clear: bool = False


# Overdue open tasks (not completed, past due_date) always float to the top, ordered by most overdue
# first. datetime() normalizes the ISO 'T'/offset form to SQLite's space-separated form so the
# comparison is chronological, not lexicographic. Non-overdue tasks keep priority/due/created order.
_TASK_ORDER_BY = (
    " ORDER BY"
    " CASE WHEN status != 'completed' AND due_date IS NOT NULL AND datetime(due_date) < datetime('now') THEN 0 ELSE 1 END ASC,"
    " CASE WHEN status != 'completed' AND due_date IS NOT NULL AND datetime(due_date) < datetime('now') THEN datetime(due_date) END ASC,"
    " priority DESC, due_date ASC NULLS LAST, created_at DESC"
)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _relative_offset(minutes: int | None, hours: int | None, days: int | None) -> timedelta | None:
    """Validated offset from --in-*/--due-in-* flags; None when no flag was given."""
    for name, val in [("minutes", minutes), ("hours", hours), ("days", days)]:
        if val is not None and val <= 0:
            raise ValueError(f"in_{name} must be positive")
    offset = timedelta(minutes=minutes or 0, hours=hours or 0, days=days or 0)
    return offset if offset.total_seconds() > 0 else None


def _parse_local_dt(datetime_str: str, timezone_str: str) -> datetime:
    try:
        local_tz = ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: '{timezone_str}'. Use IANA names like 'Europe/London' or 'America/New_York'.") from None

    parsed = datetime.fromisoformat(datetime_str)
    if parsed.tzinfo is not None:
        return parsed.astimezone(local_tz)
    return parsed.replace(tzinfo=local_tz)


def _to_utc_dt(datetime_str: str, timezone_str: str) -> datetime:
    return _parse_local_dt(datetime_str, timezone_str).astimezone(UTC)


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


def _due_field_set(due: DueSpec) -> bool:
    """Whether any due-setting field is populated (`clear` is not one of them)."""
    return due.due_datetime is not None or due.due_in_minutes is not None or due.due_in_hours is not None or due.due_in_days is not None


def _due_requested(due: DueSpec | None) -> bool:
    """Whether the spec asks for a due-date change (a timezone alone does not)."""
    return due is not None and (due.clear or _due_field_set(due))


def _compute_due_date(due: DueSpec | None) -> str | None:
    if due is None:
        return None
    if due.clear:
        if _due_field_set(due):
            raise ValueError("clear removes the due date, so it cannot be combined with a due date or offset")
        return None
    if due.due_datetime is not None:
        if due.timezone is None:
            raise ValueError("timezone is required when due_datetime is provided")
        return _to_utc(due.due_datetime, due.timezone)

    offset = _relative_offset(due.due_in_minutes, due.due_in_hours, due.due_in_days)
    if offset is not None:
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


def _require_task_row(conn, task_id: str):
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise ValueError(f"Task '{task_id}' not found. Use list to see available tasks.")
    return row


def _task_with_metadata(data_dir: Path, row: dict, include_content: bool = False) -> dict:
    task = dict(row)
    # Checkpoint bookkeeping, not task state: the ladder engine's marker means nothing to a reader.
    task.pop("checkpoint_fired_through", None)
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
    subject: str,
    due: DueSpec | None = None,
    priority: int | str = 2,
    initial_metadata: str | None = None,
) -> dict:
    priority = normalize_priority(priority)
    task_id = str(uuid.uuid4())[:8]
    due_date = _compute_due_date(due)

    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute(
            "INSERT INTO tasks (id, subject, priority, due_date) VALUES (?, ?, ?, ?)",
            (task_id, subject, priority, due_date),
        )
        conn.commit()

    if initial_metadata:
        _write_metadata(config.data_dir, task_id, initial_metadata)

    return {
        "id": task_id,
        "subject": subject,
        "status": "pending",
        "priority": priority,
        "due_date": due_date,
        "metadata_path": str(_get_metadata_path(config.data_dir, task_id)),
    }


def list_tasks(config: Config, *, show_completed: bool = False) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        query = "SELECT * FROM tasks"
        if not show_completed:
            query += " WHERE status != 'completed'"
        query += _TASK_ORDER_BY
        cursor = conn.execute(query)
        return [_task_with_metadata(config.data_dir, dict(row), include_content=False) for row in cursor]


def _backburner_update(row, *, backburner: bool | None, due_date_changed: bool, new_due_date: str | None, updates: list[str]) -> int | None:
    """The new value for the `backburner` column, or None to leave it alone.

    Parked and deadlined cannot coexist, because the checkpoint ladder would keep firing on a task
    the digest has been told to stop nagging about, which is the contradiction the flag exists to
    remove. The date is the side that wins: a real due date clears the flag whether it arrives
    alongside --backburner or on its own later, and parking a dated task drops the date, which is
    all it takes to silence the ladder since checkpoints derive from the date. Clearing a due date
    does NOT park the task; that would silence the digest as an invisible side effect of an
    unrelated command.
    """
    if new_due_date:
        return 0
    if backburner is None:
        return None
    if backburner and not due_date_changed and row["due_date"]:
        updates.append("due_date = NULL")
    return int(backburner)


def update_task(
    config: Config,
    *,
    task_id: str,
    status: str | None = None,
    subject: str | None = None,
    priority: int | str | None = None,
    due: DueSpec | None = None,
    backburner: bool | None = None,
) -> dict:
    if status and status not in ("pending", "in_progress", "completed"):
        raise ValueError(f"Status must be pending, in_progress, or completed, got {status}")
    if priority is not None:
        priority = normalize_priority(priority)

    due_date_changed = _due_requested(due)
    new_due_date = _compute_due_date(due)

    with closing(db.get_db(config.data_dir)) as conn:
        result = _require_task_row(conn, task_id)

        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            was_completed = result["status"] == "completed"
            if status == "completed":
                updates.append("completed_at = ?")
                params.append(_now_utc().isoformat())
                # A finished task stops firing: its checkpoints stop on their own because the
                # ladder only reads open tasks.
            elif was_completed:
                # Reopening from completed (to pending or in_progress). The ladder resumes on its
                # own; a pending<->in_progress toggle is not a reopen and changes nothing here.
                updates.append("completed_at = NULL")

        new_backburner = _backburner_update(
            result, backburner=backburner, due_date_changed=due_date_changed, new_due_date=new_due_date, updates=updates
        )
        for field, value in [("subject", subject), ("priority", priority), ("backburner", new_backburner)]:
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if due_date_changed:
            updates.append("due_date = ?")
            params.append(new_due_date)

        if updates:
            params.append(task_id)
            query = f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?"
            conn.execute(query, params)
            conn.commit()

        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        return _task_with_metadata(config.data_dir, dict(cursor.fetchone()), include_content=True)


def postpone_task(
    config: Config,
    *,
    task_id: str,
    due_datetime: str | None = None,
    timezone: str | None = None,
    in_minutes: int | None = None,
    in_hours: int | None = None,
    in_days: int | None = None,
) -> dict:
    """Set a new due date measured from now (or an absolute one).
    Also gives a due date to a task that never had one."""
    if due_datetime is None and not (in_minutes or in_hours or in_days):
        raise ValueError("Say when: tasks postpone <id> --in-days N (or --in-minutes/--in-hours, or --at + --tz)")
    return update_task(
        config,
        task_id=task_id,
        due=DueSpec(due_datetime=due_datetime, timezone=timezone, due_in_minutes=in_minutes, due_in_hours=in_hours, due_in_days=in_days),
    )


def get_task(config: Config, *, task_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        result = _require_task_row(conn, task_id)
        return _task_with_metadata(config.data_dir, dict(result), include_content=True)


TASK_FIELDS = (
    "id",
    "subject",
    "status",
    "priority",
    "due_date",
    "backburner",
    "created_at",
    "completed_at",
    "metadata_path",
    "metadata",
)


def get_task_fields(config: Config, *, task_id: str, fields: list[str]) -> dict:
    """Return only the requested fields; skip reading metadata unless asked."""
    unknown = [f for f in fields if f not in TASK_FIELDS]
    if unknown:
        raise ValueError(f"Unknown field(s): {', '.join(unknown)}. Valid: {', '.join(TASK_FIELDS)}")

    want_metadata = "metadata" in fields
    want_db = [f for f in fields if f not in ("metadata", "metadata_path")]

    out: dict[str, Any] = {}
    if want_db or "metadata_path" in fields:
        with closing(db.get_db(config.data_dir)) as conn:
            row = _require_task_row(conn, task_id)
            for f in want_db:
                out[f] = row[f]
            if "metadata_path" in fields:
                out["metadata_path"] = str(_get_metadata_path(config.data_dir, task_id))

    if want_metadata:
        out["metadata"] = _read_metadata(config.data_dir, task_id)

    return out


def delete_task(config: Config, *, task_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        _require_task_row(conn, task_id)
        # FK CASCADE handles linked reminders automatically
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
    _delete_metadata(config.data_dir, task_id)
    return {"status": "deleted", "task_id": task_id}


def search_tasks(config: Config, *, query: str, show_completed: bool = False) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        sql = "SELECT * FROM tasks WHERE subject LIKE ?"
        if not show_completed:
            sql += " AND status != 'completed'"
        sql += _TASK_ORDER_BY
        cursor = conn.execute(sql, (f"%{query}%",))
        return [_task_with_metadata(config.data_dir, dict(row), include_content=False) for row in cursor]


# ---------------------------------------------------------------------------
# Daily digest (overdue + stale tasks)
# ---------------------------------------------------------------------------

DIGEST_TYPE = "task_digest"
DIGEST_MIN_GAP = timedelta(hours=24)
STALE_AFTER = timedelta(days=14)
_DIGEST_META_KEY = "last_digest_at"

_OVERDUE_HEADER = (
    "Overdue tasks. Resolve every one right now: do it and `tasks done <id>`, or postpone it "
    "(`tasks postpone <id> --in-days N`), or tell the user you are dropping it and `tasks delete <id>`. "
    "Never leave a task sitting overdue."
)
_STALE_HEADER = (
    "Stale tasks, pending 2+ weeks with no due date. Give each a deadline (`tasks postpone <id> --in-days N`), "
    "do it now, drop it with the user's knowledge, or, when it is undated on purpose because someone else drives "
    "it or it is a genuine someday, park it with `tasks update <id> --backburner`: it stays pending and stays in "
    "`tasks list` marked [parked], it just stops being listed here. Never invent a deadline to buy silence."
)


def build_digest(config: Config, *, now: datetime | None = None) -> str | None:
    """The daily digest message, or None when nothing needs attention."""
    now = now or _now_utc()
    with closing(db.get_db(config.data_dir)) as conn:
        pending = conn.execute(
            "SELECT id, subject, priority, due_date, created_at, backburner FROM tasks WHERE status != 'completed'"
        ).fetchall()

    overdue: list[tuple[dict, datetime]] = []
    stale: list[tuple[dict, datetime]] = []
    for row in pending:
        if row["due_date"]:
            due = db.parse_datetime(row["due_date"])
            if due < now:
                overdue.append((dict(row), due))
        elif not row["backburner"]:
            # A backburner task is undated ON PURPOSE, so "stale" is the wrong word for it and the
            # digest's three exits (set a deadline, do it now, drop it) are all wrong actions.
            created = db.parse_datetime(row["created_at"])
            if now - created > STALE_AFTER:
                stale.append((dict(row), created))

    if not overdue and not stale:
        return None

    lines: list[str] = []
    if overdue:
        overdue.sort(key=lambda pair: pair[1])
        lines.append(_OVERDUE_HEADER)
        lines += [f'- {t["id"]} "{t["subject"]}" ({PRIORITY_LABEL[t["priority"]]}, overdue {rel_delta(now - due)})' for t, due in overdue]
    if stale:
        if overdue:
            lines.append("")
        lines.append(_STALE_HEADER)
        lines += [f'- {t["id"]} "{t["subject"]}" (created {rel_delta(now - created)} ago)' for t, created in stale]
    return "\n".join(lines)


def maybe_send_digest(config: Config, notif_dir: Path, *, now: datetime | None = None) -> bool:
    """Emit at most one task digest per day, and only when something needs attention."""
    now = now or _now_utc()
    with closing(db.get_db(config.data_dir)) as conn:
        last = db.get_meta(conn, _DIGEST_META_KEY)
    if last is not None and now - db.parse_datetime(last) < DIGEST_MIN_GAP:
        return False

    message = build_digest(config, now=now)
    if message is None:
        return False

    write_notification(notif_dir, DIGEST_TYPE, message=message)
    with closing(db.get_db(config.data_dir)) as conn:
        db.set_meta(conn, _DIGEST_META_KEY, now.isoformat())
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Due-date checkpoints (computed, never stored)
# ---------------------------------------------------------------------------

DUE_NOW_MESSAGE = (
    'Task "{subject}" ({task_id}) is due now. Decide immediately: do it and run `tasks done {task_id}`, '
    "or postpone it (`tasks postpone {task_id} --in-days N`), or tell the user you are dropping it and run "
    "`tasks delete {task_id}`. Never leave a task sitting overdue."
)

LEAD_TIME_MESSAGE = "Task due in {label}: {subject}"

# Fixed lead times before the due date, ascending; past 1 week the leads double from 2 weeks up.
# Anchor-free by design: any two computations of a task's ladder agree, so no rung list is stored.
_CHECKPOINT_TAIL = [
    ("15 minutes", timedelta(minutes=15)),
    ("1 hour", timedelta(hours=1)),
    ("1 day", timedelta(days=1)),
    ("1 week", timedelta(weeks=1)),
]
_CHECKPOINT_DOUBLING_START = timedelta(weeks=2)


def _humanize_lead(delta: timedelta) -> str:
    days = round(delta.total_seconds() / 86400)
    if days >= 60:
        return f"about {round(days / 30)} months"
    return f"about {round(days / 7)} weeks"


def checkpoint_times(due_dt: datetime, created_dt: datetime) -> list[tuple[str | None, datetime]]:
    """Every checkpoint for a due date as (label, fire time), ascending by fire time.

    A None label is the at-due decision fire. Rungs at or before the task's creation are dropped:
    they could never have fired, so they must not read as missed."""
    rungs = [(label, due_dt - delta) for label, delta in _CHECKPOINT_TAIL]
    lead = _CHECKPOINT_DOUBLING_START
    while due_dt - lead > created_dt:
        rungs.append((_humanize_lead(lead), due_dt - lead))
        lead *= 2
    rungs.append((None, due_dt))
    return sorted(((label, t) for label, t in rungs if t > created_dt), key=lambda rung: rung[1])


def fire_due_checkpoints(config: Config, notif_dir: Path, *, now: datetime | None = None) -> int:
    """Fire the newest eligible checkpoint of every open, dated task; runs each serve tick.

    checkpoint_fired_through is the single piece of state: rungs at or before it are covered.
    Only the newest uncovered rung fires, so downtime collapses to one catch-up notification per
    task instead of a backlog, and a postpone re-arms the ladder by itself because the new due
    date moves every rung past the marker. Returns the number of notifications written."""
    now = now or _now_utc()
    fired = 0
    with closing(db.get_db(config.data_dir)) as conn:
        rows = conn.execute(
            "SELECT id, subject, due_date, created_at, checkpoint_fired_through FROM tasks WHERE due_date IS NOT NULL AND status != 'completed'"
        ).fetchall()
        for row in rows:
            due_dt = db.parse_datetime(row["due_date"])
            created_dt = db.parse_datetime(row["created_at"])
            floor = db.parse_datetime(row["checkpoint_fired_through"]) if row["checkpoint_fired_through"] else created_dt
            eligible = [(label, t) for label, t in checkpoint_times(due_dt, created_dt) if floor < t <= now]
            if not eligible:
                continue
            label, _ = eligible[-1]
            if label is None:
                message = DUE_NOW_MESSAGE.format(subject=row["subject"], task_id=row["id"])
            else:
                message = LEAD_TIME_MESSAGE.format(label=label, subject=row["subject"])
            write_notification(notif_dir, "reminder", message=message, task_id=row["id"])
            conn.execute("UPDATE tasks SET checkpoint_fired_through = ? WHERE id = ?", (now.isoformat(), row["id"]))
            fired += 1
        conn.commit()
    return fired
