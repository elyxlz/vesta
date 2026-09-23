"""A cron occurrence that passes while the daemon is down is reported once on restore, as a
reminder_missed notice, and the reminder stays live; a healthy daemon never reports one."""

from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from reminders_cli import cli, commands, db
from reminders_cli.config import Config
from reminders_cli.scheduler import create_scheduler

SCHEDULES = {
    "plain": {"cron": "0 9 * * *", "tz": "UTC"},
    "fuzzed": {"cron": "0 9 * * *", "tz": "UTC", "fuzz_minutes": 10},
    "yearly": {"recurring": "yearly", "scheduled_datetime": "2026-03-14T09:00:00", "tz": "UTC"},
}


@pytest.fixture(params=list(SCHEDULES), ids=list(SCHEDULES))
def reminder(request, tmp_config: Config) -> dict:
    return commands.remind_set(tmp_config, commands.ReminderSpec(message="recurring", **SCHEDULES[request.param]))


@pytest.fixture
def notif_dir(tmp_path: Path) -> Path:
    path = tmp_path / "notifications"
    path.mkdir()
    return path


def _set_scheduled_time(config: Config, reminder_id: str, value: datetime | None):
    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute("UPDATE reminders SET scheduled_time = ? WHERE id = ?", (value.isoformat() if value else None, reminder_id))
        conn.commit()


def _row(config: Config, reminder_id: str):
    with closing(db.get_db(config.data_dir)) as conn:
        return conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()


def _missed(notif_dir: Path) -> list[Path]:
    return list(notif_dir.glob("*-reminders-reminder_missed.json"))


def _restart(config: Config, notif_dir: Path):
    scheduler = create_scheduler()
    commands.restore_all_jobs(config, scheduler, notif_dir=notif_dir)
    return scheduler


def test_no_notice_while_the_daemon_stays_up(tmp_config: Config, reminder: dict, notif_dir: Path):
    scheduler = _restart(tmp_config, notif_dir)
    commands.send_reminder_job(reminder["id"], message="recurring", data_dir=str(tmp_config.data_dir), notif_dir=str(notif_dir))
    # The fire advances the stored fire, so a daemon stopped before its next sync reports nothing on restart.
    assert db.parse_datetime(_row(tmp_config, reminder["id"])["scheduled_time"]) > datetime.now(UTC)
    # A fired fuzzed job leaves the scheduler and the job sync re-arms it.
    scheduler.remove_job(reminder["id"])
    cli._sync_jobs(tmp_config, scheduler, notif_dir)
    _restart(tmp_config, notif_dir)

    assert _missed(notif_dir) == []
    assert db.parse_datetime(_row(tmp_config, reminder["id"])["scheduled_time"]) > datetime.now(UTC)


@pytest.mark.parametrize("downtime", [timedelta(hours=25), timedelta(days=400)], ids=["one", "many"])
def test_downtime_reports_exactly_one_missed_notice(tmp_config: Config, reminder: dict, notif_dir: Path, downtime: timedelta):
    _set_scheduled_time(tmp_config, reminder["id"], datetime.now(UTC) - downtime)

    scheduler = _restart(tmp_config, notif_dir)

    assert len(_missed(notif_dir)) == 1
    row = _row(tmp_config, reminder["id"])
    assert row["completed"] == 0
    assert db.parse_datetime(row["scheduled_time"]) > datetime.now(UTC)
    assert scheduler.get_job(reminder["id"]) is not None

    _restart(tmp_config, notif_dir)
    assert len(_missed(notif_dir)) == 1


def test_no_notice_without_a_stored_fire(tmp_config: Config, reminder: dict, notif_dir: Path):
    _set_scheduled_time(tmp_config, reminder["id"], None)
    _restart(tmp_config, notif_dir)
    assert _missed(notif_dir) == []


def test_no_notice_for_an_occurrence_firing_right_now(tmp_config: Config, reminder: dict, notif_dir: Path):
    _set_scheduled_time(tmp_config, reminder["id"], datetime.now(UTC) - timedelta(seconds=5))
    _restart(tmp_config, notif_dir)
    assert _missed(notif_dir) == []
