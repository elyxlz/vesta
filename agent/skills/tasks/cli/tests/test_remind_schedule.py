"""Unit tests for recurring reminder scheduling: preset + cron triggers, DST safety, and migration."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from apscheduler.triggers.cron import CronTrigger
from tasks_cli import commands, db
from tasks_cli.config import Config


def _trigger_data(config: Config, reminder_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        row = conn.execute("SELECT trigger_data FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return json.loads(row["trigger_data"])


def _fire_days(expr: str, tz: str, start: str, count: int) -> list[str]:
    """Weekday abbreviations of the next `count` fire times of a cron expression."""
    trigger = CronTrigger.from_crontab(expr, timezone=ZoneInfo(tz))
    base = datetime.fromisoformat(start).replace(tzinfo=ZoneInfo(tz))
    out = []
    for _ in range(count):
        nxt = trigger.get_next_fire_time(None, base)
        out.append(nxt.strftime("%a").lower())
        base = nxt + timedelta(seconds=1)
    return out


# ---------------------------------------------------------------------------
# Preset recurring reminders: local wall-clock semantics + {expr, tz} storage
# ---------------------------------------------------------------------------


def test_daily_stores_local_cron_expr_and_tz(tmp_config: Config):
    result = commands.remind_set(tmp_config, message="standup", scheduled_datetime="2026-04-26T10:30:00", tz="Europe/London", recurring="daily")
    assert result["schedule"] == "daily at 10:30 Europe/London"
    assert _trigger_data(tmp_config, result["id"]) == {"type": "cron", "expr": "30 10 * * *", "tz": "Europe/London"}


def test_weekly_uses_local_day_of_week(tmp_config: Config):
    # 2026-04-26 23:30 New York is a Sunday locally (03:30 UTC Monday), so the weekly reminder must fire Sunday.
    result = commands.remind_set(
        tmp_config, message="review", scheduled_datetime="2026-04-26T23:30:00", tz="America/New_York", recurring="weekly"
    )
    assert result["schedule"] == "weekly on sun at 23:30 America/New_York"
    assert _trigger_data(tmp_config, result["id"]) == {"type": "cron", "expr": "30 23 * * sun", "tz": "America/New_York"}


def test_monthly_uses_local_day(tmp_config: Config):
    result = commands.remind_set(
        tmp_config, message="bills", scheduled_datetime="2026-04-15T23:30:00", tz="America/New_York", recurring="monthly"
    )
    assert result["schedule"] == "monthly on day 15 at 23:30 America/New_York"
    assert _trigger_data(tmp_config, result["id"]) == {"type": "cron", "expr": "30 23 15 * *", "tz": "America/New_York"}


def test_yearly_uses_local_month_and_day(tmp_config: Config):
    result = commands.remind_set(
        tmp_config, message="birthday", scheduled_datetime="2026-12-31T23:30:00", tz="America/New_York", recurring="yearly"
    )
    assert result["schedule"] == "yearly on 12/31 at 23:30 America/New_York"
    assert _trigger_data(tmp_config, result["id"]) == {"type": "cron", "expr": "30 23 31 12 *", "tz": "America/New_York"}


def test_hourly_stays_interval(tmp_config: Config):
    result = commands.remind_set(tmp_config, message="ping", recurring="hourly")
    assert result["schedule"] == "hourly"
    assert _trigger_data(tmp_config, result["id"]) == {"type": "interval", "hours": 1}


# ---------------------------------------------------------------------------
# DST safety: the whole point of storing {expr, tz} instead of a frozen UTC hour
# ---------------------------------------------------------------------------


def test_daily_preset_holds_wall_clock_across_dst(tmp_config: Config):
    """A 09:00 Europe/London daily reminder must fire at 09:00 local in both winter (UTC+0)
    and summer (UTC+1) — i.e. it must NOT drift by the DST offset."""
    result = commands.remind_set(tmp_config, message="standup", scheduled_datetime="2026-06-15T09:00:00", tz="Europe/London", recurring="daily")
    data = _trigger_data(tmp_config, result["id"])
    trigger = CronTrigger.from_crontab(data["expr"], timezone=ZoneInfo(data["tz"]))
    london = ZoneInfo("Europe/London")

    winter = trigger.get_next_fire_time(None, datetime(2026, 1, 10, tzinfo=london))
    summer = trigger.get_next_fire_time(None, datetime(2026, 7, 10, tzinfo=london))

    # Local wall-clock is 09:00 on both sides of the DST boundary.
    assert winter.astimezone(london).hour == 9
    assert summer.astimezone(london).hour == 9
    # And the underlying UTC instant shifts with the offset (09:00 UTC winter, 08:00 UTC summer).
    assert winter.astimezone(UTC).hour == 9
    assert summer.astimezone(UTC).hour == 8


# ---------------------------------------------------------------------------
# Day-of-week normalization: standard cron numbering (0/7=Sun) not APScheduler's (0=Mon)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field,expected",
    [
        ("*", "*"),
        ("?", "*"),
        ("0", "sun"),
        ("7", "sun"),
        ("1", "mon"),
        ("6", "sat"),
        ("1-5", "mon,tue,wed,thu,fri"),
        ("0,6", "sat,sun"),
        ("mon-fri", "mon,tue,wed,thu,fri"),
        ("fri-mon", "mon,fri,sat,sun"),
        ("*/2", "tue,thu,sat,sun"),
        ("sun", "sun"),
        ("MON", "mon"),
    ],
)
def test_normalize_dow(field: str, expected: str):
    assert commands._normalize_dow(field) == expected


@pytest.mark.parametrize(
    "expr,expected",
    [
        ("0 9 * * 1-5", "0 9 * * mon,tue,wed,thu,fri"),
        ("*/15 9-17 * * *", "*/15 9-17 * * *"),
        ("0 8 1 * *", "0 8 1 * *"),
        ("0 9 * * 0", "0 9 * * sun"),
    ],
)
def test_normalize_cron_expr(expr: str, expected: str):
    assert commands._normalize_cron_expr(expr) == expected


@pytest.mark.parametrize("expr", ["0 9 * *", "0 9 * * * *", "", "0 9 * * 9", "0 9 * * abc"])
def test_normalize_cron_expr_rejects_bad(expr: str):
    with pytest.raises(ValueError):
        commands._normalize_cron_expr(expr)


# ---------------------------------------------------------------------------
# Raw --cron reminders
# ---------------------------------------------------------------------------


def test_cron_weekdays_use_standard_numbering(tmp_config: Config):
    """`1-5` must mean Mon-Fri (standard cron), not Tue-Sat (raw APScheduler numbering)."""
    result = commands.remind_set(tmp_config, message="weekday standup", cron="0 9 * * 1-5", tz="America/New_York")
    data = _trigger_data(tmp_config, result["id"])
    assert data == {"type": "cron", "expr": "0 9 * * mon,tue,wed,thu,fri", "tz": "America/New_York"}
    assert result["schedule"] == "cron: 0 9 * * 1-5 (America/New_York)"
    assert result["next_run"] is not None

    days = set(_fire_days(data["expr"], data["tz"], "2026-06-01T00:00:00", 10))
    assert days == {"mon", "tue", "wed", "thu", "fri"}


def test_cron_step_expression(tmp_config: Config):
    result = commands.remind_set(tmp_config, message="quarter-hourly", cron="*/15 9-17 * * *", tz="UTC")
    data = _trigger_data(tmp_config, result["id"])
    assert data == {"type": "cron", "expr": "*/15 9-17 * * *", "tz": "UTC"}
    trigger = CronTrigger.from_crontab(data["expr"], timezone=ZoneInfo("UTC"))
    first = trigger.get_next_fire_time(None, datetime(2026, 6, 1, 8, 50, tzinfo=UTC))
    assert (first.hour, first.minute) == (9, 0)


def test_cron_requires_tz(tmp_config: Config):
    with pytest.raises(ValueError, match="tz is required"):
        commands.remind_set(tmp_config, message="x", cron="0 9 * * *")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"recurring": "daily", "scheduled_datetime": "2026-01-01T09:00:00"},
        {"scheduled_datetime": "2026-01-01T09:00:00"},
        {"in_minutes": 30},
    ],
)
def test_cron_conflicts_with_other_modes(tmp_config: Config, kwargs: dict):
    with pytest.raises(ValueError, match="cannot be combined"):
        commands.remind_set(tmp_config, message="x", cron="0 9 * * *", tz="UTC", **kwargs)


def test_cron_invalid_expression_rejected(tmp_config: Config):
    with pytest.raises(ValueError):
        commands.remind_set(tmp_config, message="x", cron="99 9 * * *", tz="UTC")


def test_cron_reminder_restores_into_scheduler(tmp_config: Config):
    from tasks_cli.scheduler import create_scheduler

    result = commands.remind_set(tmp_config, message="weekday standup", cron="0 9 * * 1-5", tz="America/New_York")
    scheduler = create_scheduler()
    commands.restore_all_jobs(tmp_config, scheduler, notif_dir=None)
    assert {job.id for job in scheduler.get_jobs()} == {result["id"]}


# ---------------------------------------------------------------------------
# Migration v2 -> v3: legacy UTC-baked cron rows become {expr, tz:"UTC"}
# ---------------------------------------------------------------------------


def _make_v2_db(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "tasks.db")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version (version) VALUES (2)")
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT, priority INTEGER, "
        "due_date TEXT, created_at TEXT, completed_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE reminders (id TEXT PRIMARY KEY, task_id TEXT, message TEXT NOT NULL, schedule_type TEXT, "
        "scheduled_time TEXT, completed INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
        "trigger_data TEXT, auto_generated INTEGER DEFAULT 0)"
    )
    return conn


def _read_trigger(data_dir: Path, rid: str) -> dict:
    with closing(db.get_db(data_dir)) as conn:
        return json.loads(conn.execute("SELECT trigger_data FROM reminders WHERE id = ?", (rid,)).fetchone()["trigger_data"])


def test_migration_v2_to_v3_rewrites_legacy_cron(tmp_path: Path):
    data_dir = tmp_path / "tasks"
    conn = _make_v2_db(data_dir)
    legacy = [
        ("daily1", {"type": "cron", "hour": 9, "minute": 0}),
        ("weekly1", {"type": "cron", "day_of_week": "fri", "hour": 17, "minute": 0}),
        ("monthly1", {"type": "cron", "day": 15, "hour": 9, "minute": 0}),
        ("interval1", {"type": "interval", "hours": 1}),
        ("date1", {"type": "date", "run_date": "2026-01-01T00:00:00+00:00"}),
    ]
    for rid, data in legacy:
        conn.execute("INSERT INTO reminders (id, message, trigger_data) VALUES (?, ?, ?)", (rid, rid, json.dumps(data)))
    conn.commit()
    conn.close()

    db.init_db(data_dir)

    assert _read_trigger(data_dir, "daily1") == {"type": "cron", "expr": "0 9 * * *", "tz": "UTC"}
    assert _read_trigger(data_dir, "weekly1") == {"type": "cron", "expr": "0 17 * * fri", "tz": "UTC"}
    assert _read_trigger(data_dir, "monthly1") == {"type": "cron", "expr": "0 9 15 * *", "tz": "UTC"}
    assert _read_trigger(data_dir, "interval1") == {"type": "interval", "hours": 1}  # non-cron untouched
    assert _read_trigger(data_dir, "date1") == {"type": "date", "run_date": "2026-01-01T00:00:00+00:00"}
    with closing(db.get_db(data_dir)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 4


def test_migration_preserves_firing_instant(tmp_path: Path):
    """A migrated legacy cron reminder must fire at the exact same UTC instant it did before."""
    data_dir = tmp_path / "tasks"
    conn = _make_v2_db(data_dir)
    conn.execute(
        "INSERT INTO reminders (id, message, trigger_data) VALUES (?, ?, ?)",
        ("daily1", "standup", json.dumps({"type": "cron", "hour": 9, "minute": 30})),
    )
    conn.commit()
    conn.close()

    db.init_db(data_dir)
    data = _read_trigger(data_dir, "daily1")
    trigger = CronTrigger.from_crontab(data["expr"], timezone=ZoneInfo(data["tz"]))
    nxt = trigger.get_next_fire_time(None, datetime(2026, 6, 1, 0, 0, tzinfo=UTC)).astimezone(UTC)
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_migration_is_idempotent(tmp_path: Path):
    data_dir = tmp_path / "tasks"
    conn = _make_v2_db(data_dir)
    conn.execute(
        "INSERT INTO reminders (id, message, trigger_data) VALUES (?, ?, ?)",
        ("daily1", "standup", json.dumps({"type": "cron", "hour": 9, "minute": 0})),
    )
    conn.commit()
    conn.close()

    db.init_db(data_dir)
    first = _read_trigger(data_dir, "daily1")
    db.init_db(data_dir)  # second run must not touch already-migrated rows
    assert _read_trigger(data_dir, "daily1") == first == {"type": "cron", "expr": "0 9 * * *", "tz": "UTC"}
