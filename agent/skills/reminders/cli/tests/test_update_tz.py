"""Repointing a live schedule's zone with `reminders update --tz`: the schedule moves, the id does not.

A recurring reminder's message is an instruction a future agent runs, and it often names its own id,
so delete-and-recreate is not a rescheduling route: the new id silently falsifies every reference to
the old one, including the ones inside reminder bodies, where no grep of the source tree reaches."""

import json
from contextlib import closing
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from reminders_cli import cli, commands, db
from reminders_cli.config import Config
from reminders_cli.scheduler import create_scheduler


def _row(config: Config, reminder_id: str):
    with closing(db.get_db(config.data_dir)) as conn:
        return conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()


def _trigger_data(config: Config, reminder_id: str) -> dict:
    return json.loads(_row(config, reminder_id)["trigger_data"])


def _daily_brief(config: Config, *, tz: str | None = None, fuzz_minutes: int | None = None) -> dict:
    spec = commands.ReminderSpec(message="morning brief", scheduled_datetime="08:45", recurring="daily", tz=tz, fuzz_minutes=fuzz_minutes)
    return commands.remind_set(config, spec)


def _repoint(config: Config, reminder_id: str, **kwargs) -> dict:
    return commands.remind_update(config, reminder_id=reminder_id, spec=commands.UpdateSpec(**kwargs))


def test_repoint_keeps_the_id_the_message_and_the_wall_clock(tmp_config: Config):
    reminder = _daily_brief(tmp_config, tz="Europe/London")

    result = _repoint(tmp_config, reminder["id"], tz="America/New_York")

    assert result["id"] == reminder["id"]
    assert result["message"] == "morning brief"
    assert _trigger_data(tmp_config, reminder["id"]) == {"type": "cron", "expr": "45 8 * * *", "tz": "America/New_York"}
    fire = db.parse_datetime(result["next_run"]).astimezone(ZoneInfo("America/New_York"))
    assert (fire.hour, fire.minute) == (8, 45)
    assert fire > datetime.now(UTC)


def test_repoint_relabels_the_zone_the_list_prints(tmp_config: Config):
    reminder = _daily_brief(tmp_config, tz="Europe/London")
    assert reminder["schedule"] == "daily at 08:45 Europe/London"

    result = _repoint(tmp_config, reminder["id"], tz="America/New_York")

    assert result["schedule"] == "daily at 08:45 America/New_York"
    listed = next(item for item in commands.remind_list(tmp_config) if item["id"] == reminder["id"])
    assert listed["schedule"] == "daily at 08:45 America/New_York"
    assert db.parse_datetime(listed["next_run"]) == db.parse_datetime(result["next_run"])


def test_repoint_a_cron_schedule_keeps_the_expression(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="weekday standup", cron="0 9 * * 1-5", tz="UTC"))
    assert reminder["schedule"] == "cron: 0 9 * * 1-5 (UTC)"

    result = _repoint(tmp_config, reminder["id"], tz="Asia/Tokyo")

    assert result["schedule"] == "cron: 0 9 * * 1-5 (Asia/Tokyo)"
    assert _trigger_data(tmp_config, reminder["id"]) == {"type": "cron", "expr": "0 9 * * mon,tue,wed,thu,fri", "tz": "Asia/Tokyo"}


def test_repoint_keeps_the_fuzz_window(tmp_config: Config):
    reminder = _daily_brief(tmp_config, tz="Europe/London", fuzz_minutes=20)
    assert reminder["schedule"] == "daily at 08:45 Europe/London, fuzz 20m"

    result = _repoint(tmp_config, reminder["id"], tz="America/New_York")

    assert result["schedule"] == "daily at 08:45 America/New_York, fuzz 20m"
    assert _trigger_data(tmp_config, reminder["id"])["fuzz_minutes"] == 20
    fire = db.parse_datetime(result["next_run"]).astimezone(ZoneInfo("America/New_York"))
    nominal = fire.replace(hour=8, minute=45, second=0, microsecond=0)
    assert abs((fire - nominal).total_seconds()) <= 20 * 60


def test_pin_a_schedule_that_followed_the_agent_zone(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    reminder = _daily_brief(tmp_config)
    assert reminder["schedule"] == "daily at 08:45"

    result = _repoint(tmp_config, reminder["id"], tz="Europe/London")

    assert result["schedule"] == "daily at 08:45 Europe/London"
    assert _trigger_data(tmp_config, reminder["id"])["tz"] == "Europe/London"


def test_unpin_returns_the_schedule_to_the_agent_zone(tmp_config: Config, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Rome")
    reminder = _daily_brief(tmp_config, tz="Europe/London")

    result = _repoint(tmp_config, reminder["id"], unpin_tz=True)

    assert result["schedule"] == "daily at 08:45"
    assert _trigger_data(tmp_config, reminder["id"]) == {"type": "cron", "expr": "45 8 * * *"}
    fire = db.parse_datetime(result["next_run"]).astimezone(ZoneInfo("Europe/Rome"))
    assert (fire.hour, fire.minute) == (8, 45)


def test_a_message_only_update_leaves_the_schedule_untouched(tmp_config: Config):
    reminder = _daily_brief(tmp_config, tz="Europe/London")
    before = _row(tmp_config, reminder["id"])

    result = commands.remind_update(tmp_config, reminder_id=reminder["id"], spec=commands.UpdateSpec(message="brief, shorter"))

    after = _row(tmp_config, reminder["id"])
    assert result["message"] == "brief, shorter"
    assert after["message"] == "brief, shorter"
    assert after["trigger_data"] == before["trigger_data"]
    assert after["schedule_type"] == before["schedule_type"]
    assert after["scheduled_time"] == before["scheduled_time"]


def test_a_one_shot_is_pointed_at_snooze(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="call back", in_hours=1))
    with pytest.raises(ValueError, match="reminders snooze"):
        _repoint(tmp_config, reminder["id"], tz="Europe/London")


def test_an_hourly_reminder_has_no_wall_clock_to_pin(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="check", recurring="hourly"))
    with pytest.raises(ValueError, match="no wall-clock time to pin"):
        _repoint(tmp_config, reminder["id"], tz="Europe/London")


def test_an_invalid_zone_is_refused_before_the_row_changes(tmp_config: Config):
    reminder = _daily_brief(tmp_config, tz="Europe/London")
    with pytest.raises(ValueError, match="Invalid timezone"):
        _repoint(tmp_config, reminder["id"], tz="Europe/Sardinia")
    assert _trigger_data(tmp_config, reminder["id"])["tz"] == "Europe/London"


def test_update_says_what_it_needs(tmp_config: Config):
    reminder = _daily_brief(tmp_config, tz="Europe/London")
    with pytest.raises(ValueError, match="Say what to change"):
        _repoint(tmp_config, reminder["id"])
    with pytest.raises(ValueError, match="Pick one zone change"):
        _repoint(tmp_config, reminder["id"], tz="Europe/London", unpin_tz=True)


@pytest.mark.parametrize("fuzz_minutes", [None, 10], ids=["plain", "fuzzed"])
def test_the_daemon_rearms_a_repointed_job_on_its_next_sync(tmp_config: Config, tmp_path, fuzz_minutes: int | None):
    """The zone change reaches the running daemon on its own: a repoint the agent has to restart the
    daemon to apply is a schedule that keeps firing in the old zone with nothing saying so."""
    reminder = _daily_brief(tmp_config, tz="Europe/London", fuzz_minutes=fuzz_minutes)
    scheduler = create_scheduler()
    scheduler.start(paused=True)
    try:
        commands.restore_all_jobs(tmp_config, scheduler, notif_dir=None)
        armed = scheduler.get_job(reminder["id"]).next_run_time
        assert armed.astimezone(ZoneInfo("Europe/London")).hour == 8

        _repoint(tmp_config, reminder["id"], tz="America/New_York")
        cli._sync_jobs(tmp_config, scheduler, tmp_path / "notifications")

        rearmed = scheduler.get_job(reminder["id"]).next_run_time
        assert rearmed != armed
        assert rearmed.astimezone(ZoneInfo("America/New_York")).hour == 8
    finally:
        scheduler.shutdown(wait=False)


def test_a_job_armed_in_the_stored_zone_is_never_rearmed(tmp_config: Config, monkeypatch):
    """A pinned and an unpinned schedule both read as current while nothing moved: a job the sync
    keeps restoring every tick would churn the scheduler for the life of the daemon."""
    monkeypatch.setenv("TZ", "Europe/Rome")
    pinned = _daily_brief(tmp_config, tz="Europe/London")
    unpinned = _daily_brief(tmp_config)
    scheduler = create_scheduler()
    scheduler.start(paused=True)
    try:
        commands.restore_all_jobs(tmp_config, scheduler, notif_dir=None)
        for reminder_id in (pinned["id"], unpinned["id"]):
            assert not commands.cron_zone_moved(scheduler.get_job(reminder_id), _trigger_data(tmp_config, reminder_id))
    finally:
        scheduler.shutdown(wait=False)
