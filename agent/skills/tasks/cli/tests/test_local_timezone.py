"""Default-local timezone semantics for absolute due dates.

An `--at` datetime without `--tz` is read in the agent's own zone (the TZ env var), stored as a
UTC instant, and echoed back with the local offset. An explicit `--tz` overrides the local zone.
"""

from contextlib import closing
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from tasks_cli import commands, db
from tasks_cli.config import Config

NY_WINTER_WALL_CLOCK = "2027-01-05T09:00:00"
NY_ZONE = "America/New_York"


def _stored_due_date(config: Config, task_id: str) -> str:
    with closing(db.get_db(config.data_dir)) as conn:
        return conn.execute("SELECT due_date FROM tasks WHERE id = ?", (task_id,)).fetchone()["due_date"]


def test_at_without_tz_is_read_in_the_agents_zone_and_stored_utc(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", NY_ZONE)
    task = commands.add_task(tmp_config, subject="local due", due=commands.DueSpec(due_datetime=NY_WINTER_WALL_CLOCK))
    expected = datetime(2027, 1, 5, 9, tzinfo=ZoneInfo(NY_ZONE))
    assert db.parse_datetime(task["due_date"]) == expected
    assert _stored_due_date(tmp_config, task["id"]) == expected.astimezone(UTC).isoformat()


def test_explicit_tz_overrides_the_agents_zone(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", NY_ZONE)
    task = commands.add_task(tmp_config, subject="tokyo due", due=commands.DueSpec(due_datetime="2027-01-05T09:00:00", timezone="Asia/Tokyo"))
    assert db.parse_datetime(task["due_date"]) == datetime(2027, 1, 5, 9, tzinfo=ZoneInfo("Asia/Tokyo"))


def test_unset_tz_env_reads_the_datetime_as_utc(tmp_config: Config, monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    task = commands.add_task(tmp_config, subject="utc due", due=commands.DueSpec(due_datetime=NY_WINTER_WALL_CLOCK))
    assert db.parse_datetime(task["due_date"]) == datetime(2027, 1, 5, 9, tzinfo=UTC)


def test_echoed_due_date_carries_the_local_offset(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", NY_ZONE)
    task = commands.add_task(tmp_config, subject="offset echo", due=commands.DueSpec(due_datetime=NY_WINTER_WALL_CLOCK))
    assert task["due_date"] == "2027-01-05T09:00:00-05:00"
    fetched = commands.get_task(tmp_config, task_id=task["id"])
    assert fetched["due_date"] == "2027-01-05T09:00:00-05:00"
    listed = commands.list_tasks(tmp_config)
    assert listed[0]["due_date"] == "2027-01-05T09:00:00-05:00"
    fields = commands.get_task_fields(tmp_config, task_id=task["id"], fields=["due_date"])
    assert fields["due_date"] == "2027-01-05T09:00:00-05:00"


def test_update_accepts_at_without_tz(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", NY_ZONE)
    task = commands.add_task(tmp_config, subject="movable")
    updated = commands.update_task(tmp_config, task_id=task["id"], due=commands.DueSpec(due_datetime=NY_WINTER_WALL_CLOCK))
    assert db.parse_datetime(updated["due_date"]) == datetime(2027, 1, 5, 9, tzinfo=ZoneInfo(NY_ZONE))


def test_postpone_accepts_at_without_tz(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", NY_ZONE)
    task = commands.add_task(tmp_config, subject="postponable")
    updated = commands.postpone_task(tmp_config, task_id=task["id"], due=commands.DueSpec(due_datetime=NY_WINTER_WALL_CLOCK))
    assert db.parse_datetime(updated["due_date"]) == datetime(2027, 1, 5, 9, tzinfo=ZoneInfo(NY_ZONE))


def test_broken_tz_env_fails_the_write_with_a_fix_or_override_hint(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", "Not/AZone")
    with pytest.raises(ValueError, match="--tz"):
        commands.add_task(tmp_config, subject="bad zone", due=commands.DueSpec(due_datetime=NY_WINTER_WALL_CLOCK))


def test_broken_tz_env_still_reads_as_utc(tmp_config: Config, monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    task = commands.add_task(tmp_config, subject="readable", due=commands.DueSpec(due_in_hours=2))
    monkeypatch.setenv("TZ", "Not/AZone")
    fetched = commands.get_task(tmp_config, task_id=task["id"])
    assert fetched["due_date"].endswith("+00:00")
