import json
import logging
import random
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

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


# Overdue pending tasks (past due_date) always float to the top, ordered by most overdue first.
# datetime() normalizes the ISO 'T'/offset form to SQLite's space-separated form so the
# comparison is chronological, not lexicographic. Non-overdue tasks keep priority/due/created order.
_TASK_ORDER_BY = (
    " ORDER BY"
    " CASE WHEN status = 'pending' AND due_date IS NOT NULL AND datetime(due_date) < datetime('now') THEN 0 ELSE 1 END ASC,"
    " CASE WHEN status = 'pending' AND due_date IS NOT NULL AND datetime(due_date) < datetime('now') THEN datetime(due_date) END ASC,"
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


def _relative_offset(minutes: int | None, hours: int | None, days: int | None) -> timedelta | None:
    """Validated offset from --in-*/--due-in-* flags; None when no flag was given."""
    for name, val in [("minutes", minutes), ("hours", hours), ("days", days)]:
        if val is not None and val <= 0:
            raise ValueError(f"in_{name} must be positive")
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
    gaps = [later - earlier for earlier, later in zip(fires, fires[1:])]
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


def _parse_local_dt(datetime_str: str, timezone_str: str) -> datetime:
    try:
        local_tz = ZoneInfo(timezone_str)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: '{timezone_str}'. Use IANA names like 'Europe/London' or 'America/New_York'.")

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


def _compute_due_date(
    due_datetime: str | None,
    timezone_str: str | None,
    due_in_minutes: int | None,
    due_in_hours: int | None,
    due_in_days: int | None,
) -> str | None:
    if due_datetime is not None:
        if timezone_str is None:
            raise ValueError("timezone is required when due_datetime is provided")
        return _to_utc(due_datetime, timezone_str)

    offset = _relative_offset(due_in_minutes, due_in_hours, due_in_days)
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
        if due_date:
            db.create_auto_reminders(conn, task_id, title, due_date)
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
        query += _TASK_ORDER_BY
        cursor = conn.execute(query)
        return [_task_with_metadata(config.data_dir, dict(row), include_content=False) for row in cursor]


def update_task(
    config: Config,
    *,
    task_id: str,
    status: str | None = None,
    title: str | None = None,
    priority: int | str | None = None,
    due_datetime: str | None = None,
    timezone: str | None = None,
    due_in_minutes: int | None = None,
    due_in_hours: int | None = None,
    due_in_days: int | None = None,
) -> dict:
    if status and status not in ("pending", "done"):
        raise ValueError(f"Status must be pending or done, got {status}")
    if priority is not None:
        priority = normalize_priority(priority)

    new_due_date: str | None = None
    due_date_changed = False
    if due_datetime is not None or due_in_minutes is not None or due_in_hours is not None or due_in_days is not None:
        new_due_date = _compute_due_date(due_datetime, timezone, due_in_minutes, due_in_hours, due_in_days)
        due_date_changed = True

    with closing(db.get_db(config.data_dir)) as conn:
        result = _require_task_row(conn, task_id)

        updates = []
        params = []

        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status == "done":
                updates.append("completed_at = ?")
                params.append(_now_utc().isoformat())
                db.delete_auto_reminders(conn, task_id)
            elif status == "pending":
                updates.append("completed_at = NULL")
                # Recreate auto-reminders if task has a due date and is reopened.
                # If due date is also being updated in this call, skip here;
                # the due-date block below handles reminder recreation with the new value.
                if not due_date_changed:
                    old_due = result["due_date"]
                    if old_due:
                        db.create_auto_reminders(conn, task_id, result["title"], old_due)

        for field, value in [("title", title), ("priority", priority)]:
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if due_date_changed:
            updates.append("due_date = ?")
            params.append(new_due_date)
            db.delete_auto_reminders(conn, task_id)
            if new_due_date:
                # Use the updated title if provided in the same call, else existing.
                reminder_title = title if title is not None else result["title"]
                # Only create reminders if the task is (or will be) pending.
                effective_status = status if status is not None else result["status"]
                if effective_status == "pending":
                    db.create_auto_reminders(conn, task_id, reminder_title, new_due_date)

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
        due_datetime=due_datetime,
        timezone=timezone,
        due_in_minutes=in_minutes,
        due_in_hours=in_hours,
        due_in_days=in_days,
    )


def get_task(config: Config, *, task_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        result = _require_task_row(conn, task_id)
        return _task_with_metadata(config.data_dir, dict(result), include_content=True)


TASK_FIELDS = (
    "id",
    "title",
    "status",
    "priority",
    "due_date",
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
        sql = "SELECT * FROM tasks WHERE title LIKE ?"
        if not show_completed:
            sql += " AND status != 'done'"
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
    "do it now, or drop it with the user's knowledge."
)


def build_digest(config: Config, *, now: datetime | None = None) -> str | None:
    """The daily digest message, or None when nothing needs attention."""
    now = now or _now_utc()
    with closing(db.get_db(config.data_dir)) as conn:
        pending = conn.execute("SELECT id, title, priority, due_date, created_at FROM tasks WHERE status = 'pending'").fetchall()

    overdue: list[tuple[dict, datetime]] = []
    stale: list[tuple[dict, datetime]] = []
    for row in pending:
        if row["due_date"]:
            due = db.parse_datetime(row["due_date"])
            if due < now:
                overdue.append((dict(row), due))
        else:
            created = db.parse_datetime(row["created_at"])
            if now - created > STALE_AFTER:
                stale.append((dict(row), created))

    if not overdue and not stale:
        return None

    lines: list[str] = []
    if overdue:
        overdue.sort(key=lambda pair: pair[1])
        lines.append(_OVERDUE_HEADER)
        lines += [f'- {t["id"]} "{t["title"]}" ({PRIORITY_LABEL[t["priority"]]}, overdue {rel_delta(now - due)})' for t, due in overdue]
    if stale:
        if overdue:
            lines.append("")
        lines.append(_STALE_HEADER)
        lines += [f'- {t["id"]} "{t["title"]}" (created {rel_delta(now - created)} ago)' for t, created in stale]
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
# Reminder job callback
# ---------------------------------------------------------------------------


def send_reminder_job(reminder_id: str, *, message: str, data_dir: str, notif_dir: str):
    """Called by APScheduler when a reminder fires."""
    data_dir = Path(data_dir)

    if notif_dir:
        task_id = None
        with closing(db.get_db(data_dir)) as conn:
            cursor = conn.execute("SELECT task_id, message, trigger_data, auto_generated FROM reminders WHERE id = ?", (reminder_id,))
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

                logger.info(f"Firing reminder {reminder_id}: {message[:50]}")

                write_reminder_notification(
                    Path(notif_dir),
                    reminder_id,
                    message,
                    task_id=task_id,
                    snooze_hint=trigger_type == "date" and not row["auto_generated"],
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
                logger.warning(f"Reminder {reminder_id}: date trigger missing 'run_date', skipping")
                return False
            run_date = db.parse_datetime(trigger_data["run_date"])
            if run_date < now:
                if run_date > now - MISSED_GRACE:
                    # Probably firing right now in a scheduler worker; a later tick either finds
                    # it completed or declares it missed for real.
                    return False
                logger.info(f"Reminder {reminder_id}: past due, sending missed notification")
                if notif_dir:
                    write_reminder_notification(
                        notif_dir,
                        reminder_id,
                        row["message"],
                        task_id=row["task_id"],
                        extra={"missed": True},
                        snooze_hint=not row["auto_generated"],
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
            logger.warning(f"Reminder {reminder_id}: unknown trigger type '{trigger_type}', skipping")
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
        if trigger_type in ("cron", "interval"):
            add_job_kwargs["misfire_grace_time"] = 3600
            add_job_kwargs["coalesce"] = True
        scheduler.add_job(**add_job_kwargs)
        logger.info(f"Restored reminder {reminder_id} ({trigger_type})")
        return True

    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error(f"Failed to restore reminder {reminder_id}: {e}")
        return False


def restore_all_jobs(config: Config, scheduler: BackgroundScheduler, *, notif_dir: Path | None = None):
    """Load all active reminders from DB and register as APScheduler jobs.
    Past-due one-time reminders fire missed notifications immediately."""
    now = _now_utc()
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute(
            "SELECT id, task_id, message, trigger_data, auto_generated FROM reminders WHERE completed = 0 AND trigger_data IS NOT NULL"
        )
        for row in cursor:
            _restore_row(scheduler, row, now, notif_dir, conn, config)
        conn.commit()


def restore_jobs_by_ids(config: Config, scheduler: BackgroundScheduler, ids: set[str], *, notif_dir: Path | None = None):
    """Restore specific reminder IDs from DB into the scheduler."""
    now = _now_utc()
    placeholders = ",".join("?" for _ in ids)
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute(
            f"SELECT id, task_id, message, trigger_data, auto_generated FROM reminders"
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


def remind_set(
    config: Config,
    *,
    message: str,
    task_id: str | None = None,
    scheduled_datetime: str | None = None,
    tz: str | None = None,
    in_minutes: int | None = None,
    in_hours: int | None = None,
    in_days: int | None = None,
    recurring: str | None = None,
    cron: str | None = None,
    fuzz_minutes: int | None = None,
    notif_dir: Path | None = None,
) -> dict:
    reminder_id = str(uuid.uuid4())[:8]
    trigger_data = None

    if fuzz_minutes is not None and cron is None and recurring not in ("daily", "weekly", "monthly", "yearly"):
        raise ValueError("fuzz_minutes needs a daily/weekly/monthly/yearly or cron schedule")

    if cron is not None:
        if recurring or scheduled_datetime or in_minutes or in_hours or in_days:
            raise ValueError("--cron cannot be combined with --recurring, --at, or --in-* options")
        if not tz:
            raise ValueError("tz is required when cron is provided")
        expr = _normalize_cron_expr(cron)
        trigger = CronTrigger.from_crontab(expr, timezone=ZoneInfo(tz))
        schedule_info = f"cron: {cron} ({tz})"
        trigger_data = {"type": "cron", "expr": expr, "tz": tz}
        next_run = trigger.get_next_fire_time(None, _now_utc())
        if fuzz_minutes is not None:
            schedule_info, next_run = _apply_fuzz(reminder_id, trigger_data, trigger, schedule_info, fuzz_minutes)
    elif recurring == "hourly":
        schedule_info = "hourly"
        trigger_data = {"type": "interval", "hours": 1}
        next_run = None
    elif recurring in ("daily", "weekly", "monthly", "yearly"):
        if not scheduled_datetime or not tz:
            raise ValueError(f"scheduled_datetime and tz are required for {recurring} reminders")
        # Build the cron expression from the user's wall-clock time and store the IANA tz alongside it,
        # so APScheduler recomputes the correct UTC instant on every fire and the reminder holds its
        # wall-clock time across DST transitions instead of drifting by the offset.
        local_dt = _parse_local_dt(scheduled_datetime, tz)
        h, m = local_dt.hour, local_dt.minute

        if recurring == "daily":
            expr = f"{m} {h} * * *"
            schedule_info = f"daily at {h:02d}:{m:02d} {tz}"
        elif recurring == "weekly":
            dow = local_dt.strftime("%a").lower()
            expr = f"{m} {h} * * {dow}"
            schedule_info = f"weekly on {dow} at {h:02d}:{m:02d} {tz}"
        elif recurring == "monthly":
            expr = f"{m} {h} {local_dt.day} * *"
            schedule_info = f"monthly on day {local_dt.day} at {h:02d}:{m:02d} {tz}"
        else:  # yearly
            expr = f"{m} {h} {local_dt.day} {local_dt.month} *"
            schedule_info = f"yearly on {local_dt.month}/{local_dt.day} at {h:02d}:{m:02d} {tz}"

        expr = _normalize_cron_expr(expr)
        trigger = CronTrigger.from_crontab(expr, timezone=ZoneInfo(tz))
        trigger_data = {"type": "cron", "expr": expr, "tz": tz}
        next_run = trigger.get_next_fire_time(None, _now_utc())
        if fuzz_minutes is not None:
            schedule_info, next_run = _apply_fuzz(reminder_id, trigger_data, trigger, schedule_info, fuzz_minutes)
    elif scheduled_datetime:
        if not tz:
            raise ValueError("tz is required when scheduled_datetime is provided")
        utc_dt = _to_utc_dt(scheduled_datetime, tz)
        schedule_info = f"once at {utc_dt.isoformat()}"
        trigger_data = {"type": "date", "run_date": utc_dt.isoformat()}
        next_run = utc_dt
    else:
        offset = _relative_offset(in_minutes, in_hours, in_days)
        if offset is None:
            raise ValueError("Must specify when to send reminder")
        run_time = _now_utc() + offset
        parts = [f"{v} {u}" for v, u in [(in_days, "days"), (in_hours, "hours"), (in_minutes, "minutes")] if v]
        schedule_info = f"once (in {' '.join(parts)})"
        trigger_data = {"type": "date", "run_date": run_time.isoformat()}
        next_run = run_time

    with closing(db.get_db(config.data_dir)) as conn:
        if task_id is not None:
            cursor = conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,))
            if not cursor.fetchone():
                raise ValueError(f"Task '{task_id}' not found")

        conn.execute(
            """INSERT OR REPLACE INTO reminders
               (id, task_id, message, schedule_type, scheduled_time, completed, trigger_data, auto_generated)
               VALUES (?, ?, ?, ?, ?, 0, ?, 0)""",
            (
                reminder_id,
                task_id,
                message,
                schedule_info,
                next_run.isoformat() if next_run else None,
                json.dumps(trigger_data) if trigger_data else None,
            ),
        )
        conn.commit()
        cursor = conn.execute("SELECT created_at FROM reminders WHERE id = ?", (reminder_id,))
        created_at = cursor.fetchone()["created_at"]

    return {
        "id": reminder_id,
        "message": message,
        "task_id": task_id,
        "schedule": schedule_info,
        "next_run": next_run.isoformat() if next_run else None,
        "created_at": created_at,
        "status": "scheduled",
    }


def remind_list(config: Config, *, task_id: str | None = None, limit: int = 50) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        if task_id is not None:
            cursor = conn.execute(
                "SELECT * FROM reminders WHERE completed = 0 AND task_id = ? ORDER BY created_at DESC LIMIT ?",
                (task_id, limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM reminders WHERE completed = 0 ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "message": row["message"],
                "schedule": row["schedule_type"],
                "next_run": row["scheduled_time"],
                "created_at": row["created_at"],
                "auto_generated": bool(row["auto_generated"]),
                "status": "pending",
            }
            for row in cursor
        ]


def remind_delete(config: Config, *, reminder_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT 1 FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        if not cursor.fetchone():
            raise ValueError(f"Reminder '{reminder_id}' not found")
        conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()

    return {"status": "deleted", "id": reminder_id}


def remind_snooze(
    config: Config,
    *,
    reminder_id: str,
    in_minutes: int | None = None,
    in_hours: int | None = None,
    in_days: int | None = None,
    at: str | None = None,
    tz: str | None = None,
) -> dict:
    """Reschedule a one-shot reminder for later; works on already-fired reminders too."""
    with closing(db.get_db(config.data_dir)) as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if not row:
            raise ValueError(f"Reminder '{reminder_id}' not found. Use 'tasks remind list' to see active reminders.")
        trigger_data = json.loads(row["trigger_data"]) if row["trigger_data"] else {}
        if "type" in trigger_data and trigger_data["type"] != "date":
            raise ValueError("Recurring reminders fire again on their own; snooze only works on one-shot reminders (delete if unwanted)")

        if at is not None:
            if not tz:
                raise ValueError("tz is required when at is provided")
            run_time = _to_utc_dt(at, tz)
        else:
            offset = _relative_offset(in_minutes, in_hours, in_days)
            if offset is None:
                raise ValueError("Say when: tasks remind snooze <id> --in-hours N (or --in-minutes/--in-days, or --at + --tz)")
            run_time = _now_utc() + offset

        new_data = {"type": "date", "run_date": run_time.isoformat()}
        conn.execute(
            "UPDATE reminders SET completed = 0, trigger_data = ?, scheduled_time = ? WHERE id = ?",
            (json.dumps(new_data), run_time.isoformat(), reminder_id),
        )
        conn.commit()

    return {"id": reminder_id, "message": row["message"], "next_run": run_time.isoformat(), "status": "snoozed"}


def remind_update(config: Config, *, reminder_id: str, message: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute("SELECT * FROM reminders WHERE id = ? AND completed = 0", (reminder_id,))
        reminder = cursor.fetchone()
        if not reminder:
            raise ValueError(f"Reminder '{reminder_id}' not found. Use 'tasks remind list' to see active reminders.")
        conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        conn.commit()

    return {
        "id": reminder_id,
        "message": message,
        "schedule": reminder["schedule_type"],
        "next_run": reminder["scheduled_time"],
        "status": "updated",
    }
