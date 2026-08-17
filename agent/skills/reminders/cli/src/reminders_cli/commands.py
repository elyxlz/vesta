import json
import logging
import os
import random
import uuid
from contextlib import closing
from datetime import UTC, datetime, time, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel

from . import db
from .config import Config
from .scheduler import write_reminder_notification

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class TriggerData(TypedDict, total=False):
    type: str
    run_date: str  # "date": one-shot ISO-8601 UTC instant
    expr: str  # "cron": normalized 5-field cron expression (day-of-week as an APScheduler name list)
    tz: str  # "cron": pinned IANA timezone (DST-aware); absent = the schedule follows the agent's own zone
    hours: int  # "interval": fixed hour spacing
    fuzz_minutes: int  # "cron": each fire shifts by a deterministic sample in [-fuzz, +fuzz]


RECURRING_TRIGGER_TYPES = ("cron", "interval")  # trigger types that fire more than once; "date" is the one-shot type

# A reminder the daemon still schedules: not fired, not soft-deleted, and carrying a trigger.
LIVE_REMINDER = "completed = 0 AND trigger_data IS NOT NULL AND deleted_at IS NULL"


class SnoozeSpec(BaseModel):
    """When a snoozed reminder should fire: from now (--in-*) or at a named moment (--at,
    in the agent's own timezone unless --tz names one). One form per call."""

    in_minutes: int | None = None
    in_hours: int | None = None
    in_days: int | None = None
    at: str | None = None
    tz: str | None = None


class ReminderSpec(BaseModel):
    """A reminder to schedule: the message plus one-shot, recurring, or cron timing."""

    message: str
    scheduled_datetime: str | None = None
    tz: str | None = None
    in_minutes: int | None = None
    in_hours: int | None = None
    in_days: int | None = None
    recurring: Literal["hourly", "daily", "weekly", "monthly", "yearly"] | None = None
    cron: str | None = None
    fuzz_minutes: int | None = None


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _zone(tz_name: str | None) -> ZoneInfo:
    """Resolve an explicit IANA name; None means the agent's own zone (boot applies the config
    store's timezone as the TZ env var)."""
    if tz_name is not None:
        try:
            return ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            raise ValueError(f"Invalid timezone: '{tz_name}'. Use IANA names like 'Europe/London' or 'America/New_York'.") from None
    local_name = os.environ["TZ"] if "TZ" in os.environ else "UTC"
    try:
        return ZoneInfo(local_name)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"The agent's TZ value '{local_name}' is not an IANA timezone. Fix the timezone config or pass --tz.") from None


def _echo_local(value: str | datetime | None) -> str | None:
    """Instants echoed in command results render in the agent's local zone; storage stays UTC.

    A broken TZ value falls back to UTC here so reads keep working; writes surface the error."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = db.parse_datetime(value)
        except ValueError:
            return value  # a malformed stored value is echoed as-is rather than hiding the row
    try:
        local_tz = _zone(None)
    except ValueError:
        local_tz = UTC
    return value.astimezone(local_tz).isoformat()


# A one-shot job whose DB run_date moved further than this into the future was snoozed after the
# job was armed; the fire is stale and the job sync re-arms it at the new time.
STALE_FIRE_SLACK = timedelta(seconds=60)

# A past-due one-shot younger than this is most likely firing right now in a scheduler worker
# (the job leaves the scheduler before completed=1 commits), not missed during downtime.
MISSED_GRACE = timedelta(seconds=30)

# How many upcoming fires to sample when bounding fuzz to half the smallest gap.
FUZZ_VALIDATION_FIRES = 26


def _relative_offset(minutes: int | None, hours: int | None, days: int | None) -> timedelta | None:
    """Validated offset from --in-* flags; None when no flag was given."""
    for name, val in [("minutes", minutes), ("hours", hours), ("days", days)]:
        if val is not None and val <= 0:
            raise ValueError(f"in_{name} must be positive")
    offset = timedelta(minutes=minutes or 0, hours=hours or 0, days=days or 0)
    return offset if offset.total_seconds() > 0 else None


def _cron_trigger_from_data(trigger_data: TriggerData) -> CronTrigger:
    # No stored tz means the schedule follows the agent's zone, resolved at build time: the daemon
    # re-arms every trigger at startup, so a timezone change plus restart moves every unpinned schedule.
    tz_name = trigger_data["tz"] if "tz" in trigger_data else None
    return CronTrigger.from_crontab(trigger_data["expr"], timezone=_zone(tz_name))


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


def _parse_local_dt(datetime_str: str, timezone_str: str | None, *, allow_bare_time: bool = False) -> datetime:
    local_tz = _zone(timezone_str)

    if allow_bare_time:
        # A schedule that only uses the wall-clock time ("daily at 21:30") should not force the
        # caller to invent a date, so a bare time anchors to today in the target timezone.
        try:
            bare = time.fromisoformat(datetime_str)
        except ValueError:
            pass
        else:
            # combine keeps the bare time's own offset when it carries one, so it lands below like any aware datetime.
            parsed = datetime.combine(datetime.now(local_tz).date(), bare)
            return parsed.astimezone(local_tz) if parsed.tzinfo is not None else parsed.replace(tzinfo=local_tz)

    parsed = datetime.fromisoformat(datetime_str)
    if parsed.tzinfo is not None:
        return parsed.astimezone(local_tz)
    return parsed.replace(tzinfo=local_tz)


def _to_utc_dt(datetime_str: str, timezone_str: str | None) -> datetime:
    return _parse_local_dt(datetime_str, timezone_str).astimezone(UTC)


# ---------------------------------------------------------------------------
# Reminder job callback
# ---------------------------------------------------------------------------


def send_reminder_job(reminder_id: str, *, message: str, data_dir: str, notif_dir: str):
    """Called by APScheduler when a reminder fires."""
    data_dir = Path(data_dir)

    if notif_dir:
        with closing(db.get_db(data_dir)) as conn:
            cursor = conn.execute("SELECT message, trigger_data, deleted_at FROM reminders WHERE id = ?", (reminder_id,))
            row = cursor.fetchone()
            if row:
                if row["deleted_at"] is not None:
                    logger.info("Reminder %s is deleted; skipping fire", reminder_id)
                    return
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
        cursor = conn.execute(f"SELECT id, message, trigger_data FROM reminders WHERE {LIVE_REMINDER}")
        for row in cursor:
            _restore_row(scheduler, row, now, notif_dir, conn, config)
        conn.commit()


def restore_jobs_by_ids(config: Config, scheduler: BackgroundScheduler, ids: set[str], *, notif_dir: Path | None = None):
    """Restore specific reminder IDs from DB into the scheduler."""
    now = _now_utc()
    placeholders = ",".join("?" for _ in ids)
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute(
            f"SELECT id, message, trigger_data FROM reminders WHERE {LIVE_REMINDER} AND id IN ({placeholders})",
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
    if not spec.scheduled_datetime:
        raise ValueError(f"scheduled_datetime is required for {spec.recurring} reminders")
    # Build the cron expression from the wall-clock time so APScheduler recomputes the correct UTC
    # instant on every fire and the reminder holds its wall-clock time across DST transitions.
    # An explicit tz is stored alongside (pinned, named in the label); without one the schedule
    # follows the agent's zone, resolved when the trigger is built.
    local_dt = _parse_local_dt(spec.scheduled_datetime, spec.tz, allow_bare_time=spec.recurring == "daily")
    h, m = local_dt.hour, local_dt.minute
    zone_label = f" {spec.tz}" if spec.tz else ""

    if spec.recurring == "daily":
        expr = f"{m} {h} * * *"
        schedule_info = f"daily at {h:02d}:{m:02d}{zone_label}"
    elif spec.recurring == "weekly":
        dow = local_dt.strftime("%a").lower()
        expr = f"{m} {h} * * {dow}"
        schedule_info = f"weekly on {dow} at {h:02d}:{m:02d}{zone_label}"
    elif spec.recurring == "monthly":
        expr = f"{m} {h} {local_dt.day} * *"
        schedule_info = f"monthly on day {local_dt.day} at {h:02d}:{m:02d}{zone_label}"
    else:  # yearly
        expr = f"{m} {h} {local_dt.day} {local_dt.month} *"
        schedule_info = f"yearly on {local_dt.month}/{local_dt.day} at {h:02d}:{m:02d}{zone_label}"

    return _cron_schedule(reminder_id, spec, expr, schedule_info)


def _cron_schedule(reminder_id: str, spec: ReminderSpec, expr: str, schedule_info: str) -> tuple[str, TriggerData, datetime | None]:
    """The stored trigger for a cron expression: pinned to spec.tz when given, fuzzed when asked."""
    trigger_data: TriggerData = {"type": "cron", "expr": _normalize_cron_expr(expr)}
    if spec.tz:
        trigger_data["tz"] = spec.tz
    trigger = _cron_trigger_from_data(trigger_data)
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
        schedule_info = f"cron: {spec.cron} ({spec.tz})" if spec.tz else f"cron: {spec.cron}"
        return _cron_schedule(reminder_id, spec, spec.cron, schedule_info)

    if spec.recurring == "hourly":
        return "hourly", {"type": "interval", "hours": 1}, None

    if spec.recurring in ("daily", "weekly", "monthly", "yearly"):
        return _recurring_trigger(reminder_id, spec)

    if spec.scheduled_datetime:
        # A one-shot is an instant: resolved in the agent's zone (or the given tz) at creation
        # time, stored as UTC, and unaffected by later timezone changes.
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
        conn.execute(
            """INSERT OR REPLACE INTO reminders
               (id, message, schedule_type, scheduled_time, completed, trigger_data)
               VALUES (?, ?, ?, ?, 0, ?)""",
            (
                reminder_id,
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
        "schedule": schedule_info,
        "next_run": _echo_local(next_run),
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
                    return _echo_local(next_fire)
            if trigger_type == "interval":
                now = _now_utc()
                stored = db.parse_datetime(row["scheduled_time"]) if row["scheduled_time"] else None
                if stored is None or stored < now:
                    hours = trigger_data["hours"] if "hours" in trigger_data else 1
                    return _echo_local(now + timedelta(hours=hours))
        except (ValueError, KeyError) as e:
            # Malformed trigger_data: fall back to the stored column rather than hiding the row.
            logger.warning("Reminder %s: cannot compute next fire from trigger_data (%s)", row["id"], e)
    return _echo_local(row["scheduled_time"])


def remind_list(config: Config, *, limit: int | None = 50, show_completed: bool = False, show_deleted: bool = False) -> list[dict]:
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
    # Two orthogonal filters, each dropped by its own flag: completed rows are hidden by default so a
    # fired one-shot (e.g. a self-chaining one re-reading its own body) stays out of the way until
    # --show-completed asks for it; soft-deleted rows are hidden until --show-deleted asks for them.
    conditions = []
    if not show_completed:
        conditions.append("completed = 0")
    if not show_deleted:
        conditions.append("deleted_at IS NULL")
    where = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    with closing(db.get_db(config.data_dir)) as conn:
        cursor = conn.execute(f"SELECT * FROM reminders {where}{order_clause}", [limit_param])
        return [_reminder_view(row) for row in cursor]


# The fields `reminders get --field` accepts: the keys of the view every read command returns.
REMINDER_FIELDS = ("id", "message", "schedule", "next_run", "created_at", "status", "deleted_at")


def _reminder_view(row) -> dict:
    return {
        "id": row["id"],
        "message": row["message"],
        "schedule": row["schedule_type"],
        "next_run": _next_run_for_row(row),
        "created_at": row["created_at"],
        "status": "completed" if row["completed"] else "pending",
        "deleted_at": row["deleted_at"],
    }


def _require_reminder_row(conn, reminder_id: str):
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if not row:
        raise ValueError(f"Reminder '{reminder_id}' not found. Use 'reminders list' to see active reminders.")
    return row


def _require_live_reminder_row(conn, reminder_id: str):
    """A row a write may change: reads still resolve a deleted reminder, but there is no undelete,
    so a write on one would report a fire time nothing ever fires at."""
    row = _require_reminder_row(conn, reminder_id)
    if row["deleted_at"] is not None:
        raise ValueError(f"Reminder '{reminder_id}' was deleted at {row['deleted_at']}; create a new reminder instead.")
    return row


def remind_get(config: Config, *, reminder_id: str) -> dict:
    """One reminder by id. A soft-deleted one still resolves, so a past id can always be inspected."""
    with closing(db.get_db(config.data_dir)) as conn:
        return _reminder_view(_require_reminder_row(conn, reminder_id))


def remind_delete(config: Config, *, reminder_id: str) -> dict:
    # A soft delete: the row stays, marked with the delete instant, so the id keeps resolving for
    # anything that referenced it. The job sync drops its live job on the next tick, and the fire
    # callback is a no-op meanwhile, so a deleted reminder never fires again.
    deleted_at = _now_utc().isoformat()
    with closing(db.get_db(config.data_dir)) as conn:
        _require_reminder_row(conn, reminder_id)
        conn.execute("UPDATE reminders SET deleted_at = ? WHERE id = ?", (deleted_at, reminder_id))
        conn.commit()

    return {"status": "deleted", "id": reminder_id, "deleted_at": deleted_at}


def remind_snooze(config: Config, *, reminder_id: str, spec: SnoozeSpec) -> dict:
    """Reschedule a one-shot reminder for later; works on already-fired reminders too.

    The result echoes previous_run and next_run so the new fire time is confirmed in the same call."""
    with closing(db.get_db(config.data_dir)) as conn:
        row = _require_live_reminder_row(conn, reminder_id)
        trigger_data = json.loads(row["trigger_data"]) if row["trigger_data"] else {}
        if "type" in trigger_data and trigger_data["type"] != "date":
            raise ValueError("Recurring reminders fire again on their own; snooze only works on one-shot reminders (delete if unwanted)")

        in_offset = _relative_offset(spec.in_minutes, spec.in_hours, spec.in_days)
        if spec.at is not None and in_offset is not None:
            raise ValueError("Pick one way to say when: --in-* (from now) or --at <iso> [--tz <tz>]")
        if spec.at is not None:
            run_time = _to_utc_dt(spec.at, spec.tz)
        elif in_offset is not None:
            run_time = _now_utc() + in_offset
        else:
            raise ValueError("Say when: reminders snooze <id> --in-hours N (from now) or --at <iso> [--tz <tz>]")

        run_time = run_time.replace(microsecond=0)
        new_data = {"type": "date", "run_date": run_time.isoformat()}
        # schedule_type is the human-readable label `reminders list` prints, so it tracks the new fire time.
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
        "previous_run": _echo_local(row["scheduled_time"]),
        "next_run": _echo_local(run_time),
        "status": "snoozed",
    }


def remind_update(config: Config, *, reminder_id: str, message: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        reminder = _require_live_reminder_row(conn, reminder_id)
        conn.execute("UPDATE reminders SET message = ? WHERE id = ?", (message, reminder_id))
        conn.commit()

    return {
        "id": reminder_id,
        "message": message,
        "schedule": reminder["schedule_type"],
        "next_run": _next_run_for_row(reminder),
        "status": "updated",
    }
