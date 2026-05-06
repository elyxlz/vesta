"""Unit tests for remind_set schedule label rendering across timezones."""

import json
from contextlib import closing
from datetime import datetime, UTC
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tasks_cli import commands, db
from tasks_cli.config import Config


@pytest.fixture
def tmp_config(tmp_path: Path) -> Config:
    cfg = Config(data_dir=tmp_path / "tasks", log_dir=tmp_path / "tasks" / "logs")
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(cfg.data_dir)
    return cfg


def _trigger_data(config: Config, reminder_id: str) -> dict:
    with closing(db.get_db(config.data_dir)) as conn:
        row = conn.execute("SELECT trigger_data FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return json.loads(row["trigger_data"])


def _expected_utc(local_iso: str, tz_name: str) -> datetime:
    return datetime.fromisoformat(local_iso).replace(tzinfo=ZoneInfo(tz_name)).astimezone(UTC)


def test_daily_label_uses_local_tz(tmp_config: Config):
    result = commands.remind_set(
        tmp_config,
        message="standup",
        scheduled_datetime="2026-04-26T10:30:00",
        tz="Europe/London",
        recurring="daily",
    )
    assert result["schedule"] == "daily at 10:30 Europe/London"
    expected_utc = _expected_utc("2026-04-26T10:30:00", "Europe/London")
    data = _trigger_data(tmp_config, result["id"])
    assert (data["hour"], data["minute"]) == (expected_utc.hour, expected_utc.minute)


def test_weekly_label_uses_local_tz_and_day(tmp_config: Config):
    result = commands.remind_set(
        tmp_config,
        message="review",
        scheduled_datetime="2026-04-26T23:30:00",
        tz="America/New_York",
        recurring="weekly",
    )
    assert result["schedule"] == "weekly on sun at 23:30 America/New_York"
    expected_utc = _expected_utc("2026-04-26T23:30:00", "America/New_York")
    data = _trigger_data(tmp_config, result["id"])
    assert (data["hour"], data["minute"]) == (expected_utc.hour, expected_utc.minute)
    assert data["day_of_week"] == expected_utc.strftime("%a").lower()


def test_monthly_label_uses_local_tz(tmp_config: Config):
    result = commands.remind_set(
        tmp_config,
        message="bills",
        scheduled_datetime="2026-04-15T23:30:00",
        tz="America/New_York",
        recurring="monthly",
    )
    assert result["schedule"] == "monthly on day 15 at 23:30 America/New_York"
    expected_utc = _expected_utc("2026-04-15T23:30:00", "America/New_York")
    data = _trigger_data(tmp_config, result["id"])
    assert (data["day"], data["hour"], data["minute"]) == (expected_utc.day, expected_utc.hour, expected_utc.minute)


def test_yearly_label_uses_local_tz(tmp_config: Config):
    result = commands.remind_set(
        tmp_config,
        message="birthday",
        scheduled_datetime="2026-12-31T23:30:00",
        tz="America/New_York",
        recurring="yearly",
    )
    assert result["schedule"] == "yearly on 12/31 at 23:30 America/New_York"
    expected_utc = _expected_utc("2026-12-31T23:30:00", "America/New_York")
    data = _trigger_data(tmp_config, result["id"])
    assert (data["month"], data["day"], data["hour"], data["minute"]) == (
        expected_utc.month,
        expected_utc.day,
        expected_utc.hour,
        expected_utc.minute,
    )


def test_daily_label_utc_tz_unchanged(tmp_config: Config):
    result = commands.remind_set(
        tmp_config,
        message="standup",
        scheduled_datetime="2026-04-26T10:30:00",
        tz="UTC",
        recurring="daily",
    )
    assert result["schedule"] == "daily at 10:30 UTC"
    data = _trigger_data(tmp_config, result["id"])
    assert (data["hour"], data["minute"]) == (10, 30)
