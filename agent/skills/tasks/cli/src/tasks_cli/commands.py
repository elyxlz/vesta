import json
import logging
import random
import uuid
from contextlib import closing
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel

from . import db
from .config import Config
from .format import PRIORITY_LABEL, rel_delta
from .scheduler import write_notification, write_reminder_notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class TriggerData(TypedDict, total=False):
    type: str
    run_date: str  # "date": one-shot ISO-8601 UTC instant
    expr: str  # "cron": normalized 5-field cron expression (day-of-week as an APScheduler name list)
    tz: str  # "cron": IANA timezone the expression is interpreted in (DST-aware)
    hours: int  # "interval": fixed hour spacing
    fuzz_minutes: int  # "cron": each fire shifts by a deterministic sample in [-fuzz, +fuzz]


RECURRING_TRIGGER_TYPES = ("cron", "interval")  # trigger types that fire more than once; "date" is the one-shot type


class DueSpec(BaseModel):
    """A task due date: an absolute datetime + timezone, or a relative due-in offset.

    The due-setting fields only move the date. `clear` is the one that unsets it, along with the
    auto reminders regenerated from it, and cannot be combined with a due-setting field.
    """

    due_datetime: str | None = None
    timezone: str | None = None
    due_in_minutes: int | None = None
    due_in_hours: int | None = None
    due_in_days: int | None = None
    clear: bool = False


class SnoozeSpec(BaseModel):
    """When a snoozed reminder should fire: from now (--in-*), from its own fire time (--by-*),
    or at a named moment (--at + --tz). One form per call."""

    in_minutes: int | None = None
    in_hours: int | None = None
    in_days: int | None = None
    by_minutes: int | None = None
    by_hours: int | None = None
    by_days: int | None = None
    at: str | None = None
    tz: str | None = None


class ReminderSpec(BaseModel):
    """A reminder to schedule: the message plus one-shot, recurring, or cron timing."""

    message: str
    task_id: str | None = None
    scheduled_datetime: str | None = None
    tz: str | None = None
    in_minutes: int | None = None
    in_hours: int | None = None
    in_days: int | None = None
    recurring: Literal["hourly", "daily", "weekly", "monthly", "yearly"] | None = None
    cron: str | None = None
    fuzz_minutes: int | None = None


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


# A one-shot job whose DB run_date moved further than this into the future was snoozed after the
# job was armed; the fire is stale and the job sync re-arms it at the new time.
STALE_FIRE_SLACK = timedelta(seconds=60)

# A past-due one-shot younger than this is most likely firing right now in a scheduler worker
# (the job leaves the scheduler before completed=1 commits), not missed during downtime.
MISSED_GRACE = timedelta(seconds=30)

# How many upcoming fires to sample when bounding fuzz to half the smallest gap.
FUZZ_VALIDATION_FIRES = 26


def _relative_offset(minutes: int | None, hours: int | None, days: int | None, *, prefix: str = "in") -> timedelta | None:
    """Validated offset from --in-*/--by-*/--due-in-* flags; None when no flag was given."""
    for name, val in [("minutes", minutes), ("hours", hours), ("days", days)]:
        if val is not None and val <= 0:
            raise ValueError(f"{prefix}_{name} must be positive")
    offset = timedelta(minutes=minutes or 0, hours=hours or 0, days=days or 0)
    return offset if offset.total_seconds() > 0 else None


def _cron_trigger_from_data(trigger_data: TriggerData) -> CronTrigger:
    return CronTrigger.from_crontab(trigger_data["expr"], timezone=ZoneInfo(trigger_data["tz"]))


def _validate_fuzz(fuzz_minutes: int, trigger: CronTrigger):
    if fuzz_minutes <= 0:
        raise ValueError("fuzz_minutes must be positive")
    # Bound against the smallest gap over the next fires, not just the first one: a weekday cron
    # validated across a weekend, or a monthly one across a long month, would otherwise accept a
    # fuzz whose windows overlap the schedule's short gaps and drop fires.
    fires: list[datetime] = []
    next_fire = trigger.get_next_fire_time(None, _now_utc())
    while next_fire is not None and len(fires) < FUZZ_VALIDATION_FIRES:
        fires.append(next_fire)
        next_fire = trigger.get_next_fire_time(next_fire, next_fire + timedelta(seconds=1))
    gaps = [later - earlier for earlier, later in pairwise(fires)]
    if not gaps or timedelta(minutes=fuzz_minutes) > min(gaps) / 2:
        raise ValueError("fuzz_minutes must be at most half the gap between fires")


def fuzzed_next_fire(reminder_id: str, trigger_data: TriggerData, after: datetime) -> datetime:
    """Next fire instant for a fuzzed cron reminder: the nominal cron fire shifted by an offset
    sampled deterministically per (reminder, nominal instant). A daemon restart recomputes the
    identical instant, so fuzz can neither double-fire nor drift across restarts."""
    trigger = _cron_trigger_from_data(trigger_data)
    fuzz = timedelta(minutes=trigger_data["fuzz_minutes"])
    nominal = trigger.get_next_fire_time(None, after - fuzz)
    while True:
        offset = random.Random(f"{reminder_id}@{nominal.isoformat()}").uniform(-1.0, 1.0)
        fire = nominal + fuzz * offset
        if fire > after:
            return fire
        nominal = trigger.get_next_fire_time(nominal, nominal + timedelta(seconds=1))


# Standard cron numbers the day-of-week field 0-7 with 0 and 7 both Sunday (1=Mon .. 6=Sat) and is
# what every crontab, doc, and LLM assumes. APScheduler's from_crontab instead uses 0=Mon .. 6=Sun and
# rejects 7, so "* * * * 1-5" would silently fire Tue-Sat. We normalize the day-of-week field to an
# unambiguous list of APScheduler weekday names, which both dialects agree on, before handing it over.
_VIXIE_DOW_NAMES = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")  # index = standard-cron number, 0=Sunday
_DOW_NAME_TO_INDEX = {name: i for i, name in enumerate(_VIXIE_DOW_NAMES)}
_APSCHEDULER_DOW_ORDER = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _dow_single(token: str) -> int:
    tok = token.strip().lower()
    if tok in _DOW_NAME_TO_INDEX:
        return _DOW_NAME_TO_INDEX[tok]
    if not tok.isdigit():
        raise ValueError(f"Invalid day-of-week value: '{token}' (use 0-7 or sun-sat)")
    number = int(tok)
    if number == 7:
        return 0
    if 0 <= number <= 6:
        return number
    raise ValueError(f"Invalid day-of-week value: '{token}' (use 0-7 or sun-sat)")


def _dow_part_to_indices(part: str) -> list[int]:
    """Expand one comma-separated piece of a standard-cron day-of-week field to indices (0=Sun .. 6=Sat)."""
    step = 1
    if "/" in part:
        part, _, step_str = part.partition("/")
        if not step_str.isdigit() or int(step_str) <= 0:
            raise ValueError(f"Invalid day-of-week step: '{step_str}'")
        step = int(step_str)

    if part.strip() in ("*", "?"):
        low, high = 0, 6
    elif "-" in part:
        low_str, _, high_str = part.partition("-")
        low, high = _dow_single(low_str), _dow_single(high_str)
    else:
        low = high = _dow_single(part)

    span = (high - low) % 7  # standard cron allows wrap-around ranges like fri-mon
    return [(low + offset) % 7 for offset in range(0, span + 1, step)]


def _normalize_dow(field: str) -> str:
    if field.strip() in ("*", "?"):
        return "*"
    indices: set[int] = set()
    for part in field.split(","):
        indices.update(_dow_part_to_indices(part))
    names = sorted((_VIXIE_DOW_NAMES[i] for i in indices), key=_APSCHEDULER_DOW_ORDER.index)
    return ",".join(names)


def _normalize_cron_expr(expr: str) -> str:
    """Validate a 5-field cron expression and rewrite its day-of-week field to standard-cron semantics."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"Cron expression must have 5 fields (min hour day month dow), got {len(fields)}: '{expr}'")
    fields[4] = _normalize_dow(fields[4])
    return " ".join(fields)


def _parse_local_dt(datetime_str: str, timezone_str: str, *, allow_bare_time: bool = False) -> datetime:
    try:
        local_tz = ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: '{timezone_str}'. Use IANA names like 'Europe/London' or 'America/New_York'.") from None

    if allow_bare_time:
        # A schedule that only uses the wall-clock time ("daily at 21:30") should not force the
        # caller to invent a date, so a bare time anchors to today in the target timezone.
        try:
            bare = time.fromisoformat(datetime_str)
        except ValueError:
            pass
        else:
            return datetime.combine(datetime.now(local_tz).date(), bare, tzinfo=local_tz)

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
                # A finished task stops reminding entirely: its linked reminders are cleared here,
                # and its checkpoints stop on their own because the ladder only reads open tasks.
                db.delete_task_reminders(conn, task_id)
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
    """Set a new due date measured from now (or an absolute one) and rebuild the auto reminders.
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
                trigger_type = trigger_data["type"] if "type" in trigger_data else None

                if trigger_type == "date" and "run_date" in trigger_data:
                    run_date = db.parse_datetime(trigger_data["run_date"])
                    if run_date > _now_utc() + STALE_FIRE_SLACK:
                        logger.info("Reminder %s was snoozed to %s; skipping stale fire", reminder_id, trigger_data["run_date"])
                        return

                logger.info("Firing reminder %s: %s", reminder_id, message[:50])

                write_reminder_notification(
                    Path(notif_dir),
                    reminder_id,
                    message,
                    task_id=task_id,
                    snooze_hint=trigger_type == "date",
                )

                if trigger_type == "date":
                    conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                    conn.commit()
                elif trigger_type == "cron" and "fuzz_minutes" not in trigger_data:
                    # Fuzzed cron rows run as chained one-shots; the job sync's restore computes
                    # their next fuzzed fire and advances scheduled_time, so only plain cron
                    # (whose job stays armed) updates it here.
                    next_fire = _cron_trigger_from_data(trigger_data).get_next_fire_time(None, _now_utc())
                    if next_fire is not None:
                        conn.execute(
                            "UPDATE reminders SET scheduled_time = ? WHERE id = ?",
                            (next_fire.isoformat(), reminder_id),
                        )
                        conn.commit()
                elif trigger_type == "interval":
                    hours = trigger_data["hours"] if "hours" in trigger_data else 1
                    next_fire = _now_utc() + timedelta(hours=hours)
                    conn.execute(
                        "UPDATE reminders SET scheduled_time = ? WHERE id = ?",
                        (next_fire.isoformat(), reminder_id),
                    )
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
                logger.warning("Reminder %s: date trigger missing 'run_date', skipping", reminder_id)
                return False
            run_date = db.parse_datetime(trigger_data["run_date"])
            if run_date < now:
                if run_date > now - MISSED_GRACE:
                    # Probably firing right now in a scheduler worker; a later tick either finds
                    # it completed or declares it missed for real.
                    return False
                logger.info("Reminder %s: past due, sending missed notification", reminder_id)
                if notif_dir:
                    write_reminder_notification(
                        notif_dir,
                        reminder_id,
                        row["message"],
                        task_id=row["task_id"],
                        extra={"missed": True},
                        snooze_hint=True,
                    )
                conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder_id,))
                return True
            trigger = DateTrigger(run_date=run_date)

        elif trigger_type == "cron":
            if "fuzz_minutes" in trigger_data:
                # Fuzzed reminders run as chained one-shots: this job fires once at the fuzzed
                # instant, then the serve loop's job sync restores the next one the same way.
                fire = fuzzed_next_fire(reminder_id, trigger_data, now)
                conn.execute("UPDATE reminders SET scheduled_time = ? WHERE id = ?", (fire.isoformat(), reminder_id))
                trigger = DateTrigger(run_date=fire)
            else:
                trigger = _cron_trigger_from_data(trigger_data)

        elif trigger_type == "interval":
            trigger = IntervalTrigger(hours=trigger_data["hours"] if "hours" in trigger_data else 1)

        else:
            logger.warning("Reminder %s: unknown trigger type '%s', skipping", reminder_id, trigger_type)
            return False

        add_job_kwargs: dict = {
            "func": send_reminder_job,
            "trigger": trigger,
            "args": [reminder_id],
            "kwargs": {
                "message": row["message"],
                "data_dir": str(config.data_dir),
                "notif_dir": str(notif_dir) if notif_dir else "",
            },
            "id": reminder_id,
            "replace_existing": True,
        }
        if trigger_type in RECURRING_TRIGGER_TYPES:
            add_job_kwargs["misfire_grace_time"] = 3600
            add_job_kwargs["coalesce"] = True
        scheduler.add_job(**add_job_kwargs)
        logger.info("Restored reminder %s (%s)", reminder_id, trigger_type)
        return True

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Failed to restore reminder %s: %s", reminder_id, e)
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
            f"SELECT id, task_id, message, trigger_data FROM reminders"
            f" WHERE completed = 0 AND trigger_data IS NOT NULL AND id IN ({placeholders})",
            list(ids),
        )
        for row in cursor:
            _restore_row(scheduler, row, now, notif_dir, conn, config)
        conn.commit()


# ---------------------------------------------------------------------------
# Reminder commands (CRUD)
# ---------------------------------------------------------------------------


def _apply_fuzz(
    reminder_id: str, trigger_data: TriggerData, trigger: CronTrigger, schedule_info: str, fuzz_minutes: int
) -> tuple[str, datetime]:
    _validate_fuzz(fuzz_minutes, trigger)
    trigger_data["fuzz_minutes"] = fuzz_minutes
    return f"{schedule_info}, fuzz {fuzz_minutes}m", fuzzed_next_fire(reminder_id, trigger_data, _now_utc())


def _recurring_trigger(reminder_id: str, spec: ReminderSpec) -> tuple[str, TriggerData, datetime | None]:
    if not spec.scheduled_datetime or not spec.tz:
        raise ValueError(f"scheduled_datetime and tz are required for {spec.recurring} reminders")
    # Build the cron expression from the user's wall-clock time and store the IANA tz alongside it,
    # so APScheduler recomputes the correct UTC instant on every fire and the reminder holds its
    # wall-clock time across DST transitions instead of drifting by the offset.
    local_dt = _parse_local_dt(spec.scheduled_datetime, spec.tz, allow_bare_time=spec.recurring == "daily")
    h, m = local_dt.hour, local_dt.minute

    if spec.recurring == "daily":
        expr = f"{m} {h} * * *"
        schedule_info = f"daily at {h:02d}:{m:02d} {spec.tz}"
    elif spec.recurring == "weekly":
        dow = local_dt.strftime("%a").lower()
        expr = f"{m} {h} * * {dow}"
        schedule_info = f"weekly on {dow} at {h:02d}:{m:02d} {spec.tz}"
    elif spec.recurring == "monthly":
        expr = f"{m} {h} {local_dt.day} * *"
        schedule_info = f"monthly on day {local_dt.day} at {h:02d}:{m:02d} {spec.tz}"
    else:  # yearly
        expr = f"{m} {h} {local_dt.day} {local_dt.month} *"
        schedule_info = f"yearly on {local_dt.month}/{local_dt.day} at {h:02d}:{m:02d} {spec.tz}"

    expr = _normalize_cron_expr(expr)
    trigger = CronTrigger.from_crontab(expr, timezone=ZoneInfo(spec.tz))
    trigger_data: TriggerData = {"type": "cron", "expr": expr, "tz": spec.tz}
    next_run = trigger.get_next_fire_time(None, _now_utc())
    if spec.fuzz_minutes is not None:
        schedule_info, next_run = _apply_fuzz(reminder_id, trigger_data, trigger, schedule_info, spec.fuzz_minutes)
    return schedule_info, trigger_data, next_run


def _build_trigger(reminder_id: str, spec: ReminderSpec) -> tuple[str, TriggerData, datetime | None]:
    """Resolve a reminder spec to (schedule_info, trigger_data, next_run)."""
    if spec.fuzz_minutes is not None and spec.cron is None and spec.recurring not in ("daily", "weekly", "monthly", "yearly"):
        raise ValueError("fuzz_minutes needs a daily/weekly/monthly/yearly or cron schedule")

    if spec.cron is not None:
        if spec.recurring or spec.scheduled_datetime or spec.in_minutes or spec.in_hours or spec.in_days:
            raise ValueError("--cron cannot be combined with --recurring, --at, or --in-* options")
        if not spec.tz:
            raise ValueError("tz is required when cron is provided")
        expr = _normalize_cron_expr(spec.cron)
        trigger = CronTrigger.from_crontab(expr, timezone=ZoneInfo(spec.tz))
        schedule_info = f"cron: {spec.cron} ({spec.tz})"
        trigger_data: TriggerData = {"type": "cron", "expr": expr, "tz": spec.tz}
        next_run = trigger.get_next_fire_time(None, _now_utc())
        if spec.fuzz_minutes is not None:
            schedule_info, next_run = _apply_fuzz(reminder_id, trigger_data, trigger, schedule_info, spec.fuzz_minutes)
        return schedule_info, trigger_data, next_run

    if spec.recurring == "hourly":
        return "hourly", {"type": "interval", "hours": 1}, None

    if spec.recurring in ("daily", "weekly", "monthly", "yearly"):
        return _recurring_trigger(reminder_id, spec)

    if spec.scheduled_datetime:
        if not spec.tz:
            raise ValueError("tz is required when scheduled_datetime is provided")
        utc_dt = _to_utc_dt(spec.scheduled_datetime, spec.tz)
        return f"once at {utc_dt.isoformat()}", {"type": "date", "run_date": utc_dt.isoformat()}, utc_dt

    offset = _relative_offset(spec.in_minutes, spec.in_hours, spec.in_days)
    if offset is None:
        raise ValueError("Must specify when to send reminder")
    run_time = _now_utc() + offset
    parts = [f"{v} {u}" for v, u in [(spec.in_days, "days"), (spec.in_hours, "hours"), (spec.in_minutes, "minutes")] if v]
    return f"once (in {' '.join(parts)})", {"type": "date", "run_date": run_time.isoformat()}, run_time


def remind_set(config: Config, spec: ReminderSpec) -> dict:
    reminder_id = str(uuid.uuid4())[:8]
    schedule_info, trigger_data, next_run = _build_trigger(reminder_id, spec)

    with closing(db.get_db(config.data_dir)) as conn:
        if spec.task_id is not None:
            cursor = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (spec.task_id,))
            if not cursor.fetchone():
                raise ValueError(f"Task '{spec.task_id}' not found")

        conn.execute(
            """INSERT OR REPLACE INTO reminders
               (id, task_id, message, schedule_type, scheduled_time, completed, trigger_data)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (
                reminder_id,
                spec.task_id,
                spec.message,
                schedule_info,
                next_run.isoformat() if next_run else None,
                json.dumps(trigger_data),
            ),
        )
        conn.commit()
        cursor = conn.execute("SELECT created_at FROM reminders WHERE id = ?", (reminder_id,))
        created_at = cursor.fetchone()["created_at"]

    return {
        "id": reminder_id,
        "message": spec.message,
        "task_id": spec.task_id,
        "schedule": schedule_info,
        "next_run": next_run.isoformat() if next_run else None,
        "created_at": created_at,
        "status": "scheduled",
    }


def _next_run_for_row(row) -> str | None:
    """The next fire instant to report for a reminder row.

    A recurring row's `scheduled_time` only advances when the job fires, so downtime longer than one
    period strands it in the past while the restored trigger is armed and correct. Plain cron is
    recomputed exactly from its expression. An interval row's true next fire depends on when the
    daemon restored it, which the row does not record, so a stale column is clamped to the upper
    bound the restored `IntervalTrigger` can reach; that is imprecise but never in the past, and a
    past instant is the one answer guaranteed to be wrong. Fuzzed cron, date and one-shot rows keep
    the column, which the restore path does keep live for them.
    """
    if row["trigger_data"]:
        try:
            trigger_data = json.loads(row["trigger_data"])
            trigger_type = trigger_data["type"] if "type" in trigger_data else None
            if trigger_type == "cron" and "fuzz_minutes" not in trigger_data:
                next_fire = _cron_trigger_from_data(trigger_data).get_next_fire_time(None, _now_utc())
                if next_fire is not None:
                    return next_fire.isoformat()
            if trigger_type == "interval":
                now = _now_utc()
                stored = db.parse_datetime(row["scheduled_time"]) if row["scheduled_time"] else None
                if stored is None or stored < now:
                    hours = trigger_data["hours"] if "hours" in trigger_data else 1
                    return (now + timedelta(hours=hours)).isoformat()
        except (ValueError, KeyError):
            pass  # malformed trigger_data: fall back to the stored column rather than hiding the row
    return row["scheduled_time"]


def remind_list(config: Config, *, task_id: str | None = None, limit: int | None = 50, show_completed: bool = False) -> list[dict]:
    # limit=None means every row: SQLite reads LIMIT -1 as unlimited.
    limit_param = -1 if limit is None else limit
    # Three rank groups, so a cut (this LIMIT, or the table page in cli.py) only ever trims the
    # tail: recurring rows first by created_at (a plain cron row's scheduled_time records its last
    # advance, not its next fire, so it is not a sound sort key for them), then pending one-shots
    # by fire time so the cut drops the furthest-out rows and "what fires next" stays visible,
    # then fired one-shots newest first, so under --show-completed a backlog of old fired rows can
    # never page out the live rows or the just-fired one being recovered.
    recurring_types = ", ".join(f"'{t}'" for t in RECURRING_TRIGGER_TYPES)
    is_recurring = f"json_extract(trigger_data, '$.type') IN ({recurring_types})"
    rank = f"CASE WHEN {is_recurring} THEN 0 WHEN completed THEN 2 ELSE 1 END"
    order_clause = (
        f"ORDER BY {rank}, "
        f"CASE WHEN {is_recurring} THEN created_at WHEN completed THEN scheduled_time END DESC, "
        f"CASE WHEN {is_recurring} OR completed THEN NULL ELSE scheduled_time END ASC "
        "LIMIT ?"
    )
    # completed rows are hidden by default; --show-completed drops that filter so a reminder that
    # has already fired (e.g. a self-chaining one re-reading its own body) is still retrievable.
    filters = ([] if show_completed else ["completed = 0"]) + ([] if task_id is None else ["task_id = ?"])
    where = f"WHERE {' AND '.join(filters)} " if filters else ""
    params = ([] if task_id is None else [task_id]) + [limit_param]
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute(f"SELECT * FROM reminders {where}{order_clause}", params)
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "message": row["message"],
                "schedule": row["schedule_type"],
                "next_run": _next_run_for_row(row),
                "created_at": row["created_at"],
                "status": "completed" if row["completed"] else "pending",
            }
            for row in cursor
        ]


def remind_delete(config: Config, *, reminder_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT 1 FROM reminders WHERE id = ?", (reminder_id,))
        if not cursor.fetchone():
            raise ValueError(f"Reminder '{reminder_id}' not found")
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()

    return {"status": "deleted", "id": reminder_id}


def remind_snooze(config: Config, *, reminder_id: str, spec: SnoozeSpec) -> dict:
    """Reschedule a one-shot reminder for later; works on already-fired reminders too.

    The result echoes previous_run and next_run so a misread of the from-now vs from-fire-time
    difference is visible the moment it happens."""
    with closing(db.get_db(config.data_dir)) as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if not row:
            raise ValueError(f"Reminder '{reminder_id}' not found. Use 'tasks remind list' to see active reminders.")
        trigger_data = json.loads(row["trigger_data"]) if row["trigger_data"] else {}
        if "type" in trigger_data and trigger_data["type"] != "date":
            raise ValueError("Recurring reminders fire again on their own; snooze only works on one-shot reminders (delete if unwanted)")

        in_offset = _relative_offset(spec.in_minutes, spec.in_hours, spec.in_days)
        by_offset = _relative_offset(spec.by_minutes, spec.by_hours, spec.by_days, prefix="by")
        given = [form for form in (spec.at, in_offset, by_offset) if form is not None]
        if len(given) > 1:
            raise ValueError("Pick one way to say when: --in-* (from now), --by-* (from the fire time), or --at + --tz")
        if spec.at is not None:
            if not spec.tz:
                raise ValueError("tz is required when at is provided")
            run_time = _to_utc_dt(spec.at, spec.tz)
        elif in_offset is not None:
            run_time = _now_utc() + in_offset
        elif by_offset is not None:
            if not row["scheduled_time"]:
                raise ValueError("This reminder has no fire time to shift from; use --in-* or --at + --tz")
            run_time = db.parse_datetime(row["scheduled_time"]) + by_offset
        else:
            raise ValueError("Say when: tasks remind snooze <id> --in-hours N (from now), --by-hours N (from the fire time), or --at + --tz")

        run_time = run_time.replace(microsecond=0)
        new_data = {"type": "date", "run_date": run_time.isoformat()}
        # schedule_type is the human-readable label `remind list` prints, so it tracks the new fire time.
        new_schedule = f"once at {run_time.isoformat()}"
        conn.execute(
            "UPDATE reminders SET completed = 0, trigger_data = ?, scheduled_time = ?, schedule_type = ? WHERE id = ?",
            (json.dumps(new_data), run_time.isoformat(), new_schedule, reminder_id),
        )
        conn.commit()

    return {
        "id": reminder_id,
        "message": row["message"],
        "schedule": new_schedule,
        "previous_run": row["scheduled_time"],
        "next_run": run_time.isoformat(),
        "status": "snoozed",
    }


def remind_update(config: Config, *, reminder_id: str, message: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
        reminder = cursor.fetchone()
        if not reminder:
            raise ValueError(f"Reminder '{reminder_id}' not found. Use 'tasks remind list' to see active reminders.")
        conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        conn.commit()

    return {
        "id": reminder_id,
        "message": message,
        "schedule": reminder["schedule_type"],
        "next_run": _next_run_for_row(reminder),
        "status": "updated",
    }
