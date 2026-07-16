"""Unit tests for fuzzed recurring reminders: deterministic sampling, window bounds, restart safety."""

from datetime import UTC, datetime, timedelta

import pytest
from tasks_cli import commands, db
from tasks_cli.config import Config

DAILY_1030 = {"type": "cron", "expr": "30 10 * * *", "tz": "UTC", "fuzz_minutes": 60}


def test_fuzz_stored_and_next_run_within_window(tmp_config: Config):
    result = commands.remind_set(
        tmp_config, message="wind down", scheduled_datetime="2026-04-26T21:30:00", tz="UTC", recurring="daily", fuzz_minutes=45
    )
    assert result["schedule"] == "daily at 21:30 UTC, fuzz 45m"

    # A 45m fuzz around 21:30 stays inside the same date, so the nominal is next_run's own 21:30.
    next_run = db.parse_datetime(result["next_run"])
    nominal = next_run.replace(hour=21, minute=30, second=0, microsecond=0)
    assert abs((next_run - nominal).total_seconds()) <= 45 * 60


def test_fuzz_requires_a_recurring_or_cron_schedule(tmp_config: Config):
    with pytest.raises(ValueError, match="fuzz_minutes needs"):
        commands.remind_set(tmp_config, message="one shot", in_hours=1, fuzz_minutes=30)
    with pytest.raises(ValueError, match="fuzz_minutes needs"):
        commands.remind_set(tmp_config, message="hourly", recurring="hourly", fuzz_minutes=30)


def test_fuzz_bounded_by_smallest_gap_not_first(tmp_config: Config):
    # Weekday cron: the weekend gap is 3 days but the weekday gap is 24h, so 800m (> 720m half) is
    # rejected no matter which gap comes next.
    with pytest.raises(ValueError, match="half the gap"):
        commands.remind_set(tmp_config, message="weekdays", cron="0 9 * * 1-5", tz="UTC", fuzz_minutes=800)


def test_fuzz_must_fit_in_half_the_period(tmp_config: Config):
    with pytest.raises(ValueError, match="half the gap"):
        commands.remind_set(
            tmp_config, message="too wide", scheduled_datetime="2026-04-26T10:30:00", tz="UTC", recurring="daily", fuzz_minutes=800
        )
    with pytest.raises(ValueError, match="positive"):
        commands.remind_set(
            tmp_config, message="negative", scheduled_datetime="2026-04-26T10:30:00", tz="UTC", recurring="daily", fuzz_minutes=-5
        )


def test_fuzzed_next_fire_is_deterministic_and_bounded():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    first = commands.fuzzed_next_fire("rem1", DAILY_1030, after)
    again = commands.fuzzed_next_fire("rem1", DAILY_1030, after)
    assert first == again

    nominal = datetime(2026, 1, 1, 10, 30, tzinfo=UTC)
    assert abs((first - nominal).total_seconds()) <= 60 * 60

    other = commands.fuzzed_next_fire("rem2", DAILY_1030, after)
    assert other != first  # distinct reminders sample distinct offsets


def test_fuzzed_next_fire_never_double_fires_across_restarts():
    after = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    fire = commands.fuzzed_next_fire("rem1", DAILY_1030, after)

    # A restart moments before the fire recomputes the identical instant.
    assert commands.fuzzed_next_fire("rem1", DAILY_1030, fire - timedelta(minutes=1)) == fire

    # A restart (or the post-fire resync) right after the fire moves to the next day,
    # even while today's nominal 10:30 may still be ahead of the clock.
    following = commands.fuzzed_next_fire("rem1", DAILY_1030, fire)
    assert following > fire
    assert following - fire > timedelta(hours=12)
