"""Soft delete: `reminders delete` keeps the row, marks it deleted, and stops it firing again.

Deleting a reminder stamps it with a delete instant instead of removing the row, so a past id still
resolves. The reminder drops off the default list, never re-arms on restart, and its fire callback
is a no-op, so a delete racing the daemon's next sync tick can never write a stray notification.
"""

from contextlib import closing
from pathlib import Path

import pytest
from reminders_cli import commands, db
from reminders_cli import format as fmt
from reminders_cli.commands import send_reminder_job
from reminders_cli.config import Config
from reminders_cli.scheduler import create_scheduler


def _row(cfg: Config, reminder_id: str):
    with closing(db.get_db(cfg.data_dir)) as conn:
        return conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()


def test_delete_keeps_the_row_and_stamps_deleted_at(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="bye", in_minutes=30))
    result = commands.remind_delete(tmp_config, reminder_id=reminder["id"])
    assert result["status"] == "deleted"
    row = _row(tmp_config, reminder["id"])
    assert row is not None, "soft delete must keep the row"
    assert row["deleted_at"] is not None


@pytest.mark.parametrize(
    "write",
    [
        lambda cfg, rid: commands.remind_snooze(cfg, reminder_id=rid, spec=commands.SnoozeSpec(in_hours=2)),
        lambda cfg, rid: commands.remind_update(cfg, reminder_id=rid, spec=commands.UpdateSpec(message="renamed")),
        lambda cfg, rid: commands.remind_update(cfg, reminder_id=rid, spec=commands.UpdateSpec(tz="Europe/London")),
    ],
    ids=["snooze", "update-message", "update-tz"],
)
def test_writes_on_a_deleted_reminder_are_refused(tmp_config: Config, write):
    """There is no undelete: a snooze that succeeded would report a fire time nothing ever fires at."""
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="gone", in_minutes=30))
    commands.remind_delete(tmp_config, reminder_id=reminder["id"])
    with pytest.raises(ValueError, match="was deleted"):
        write(tmp_config, reminder["id"])
    assert commands.remind_get(tmp_config, reminder_id=reminder["id"])["message"] == "gone"


def test_deleted_reminder_absent_from_default_list(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="gone", in_minutes=30))
    commands.remind_delete(tmp_config, reminder_id=reminder["id"])
    assert not any(item["id"] == reminder["id"] for item in commands.remind_list(tmp_config))


def test_show_deleted_reveals_the_row(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="gone", in_minutes=30))
    commands.remind_delete(tmp_config, reminder_id=reminder["id"])
    listed = {item["id"]: item for item in commands.remind_list(tmp_config, show_deleted=True)}
    assert reminder["id"] in listed
    assert listed[reminder["id"]]["deleted_at"] is not None


def test_table_marks_deleted_rows(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="gone", in_minutes=30))
    commands.remind_delete(tmp_config, reminder_id=reminder["id"])
    rendered = fmt.format_reminder_list(commands.remind_list(tmp_config, show_deleted=True))
    assert "[deleted]" in rendered


def test_deleted_reminder_not_rearmed_on_restart(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="weekday standup", cron="0 9 * * 1-5", tz="America/New_York"))
    commands.remind_delete(tmp_config, reminder_id=reminder["id"])
    scheduler = create_scheduler()
    commands.restore_all_jobs(tmp_config, scheduler, notif_dir=None)
    assert {job.id for job in scheduler.get_jobs()} == set()


def test_fire_callback_is_a_no_op_for_a_deleted_reminder(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="do not fire", in_minutes=1))
    commands.remind_delete(tmp_config, reminder_id=reminder["id"])
    send_reminder_job(reminder["id"], message="do not fire", data_dir=str(tmp_config.data_dir), notif_dir=str(notif_dir))
    assert list(notif_dir.glob("*-reminders-reminder.json")) == []
