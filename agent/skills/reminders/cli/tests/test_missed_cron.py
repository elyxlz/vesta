"""A recurring cron fire that came due while the daemon was down is reported once at startup.

Founding case, 11 Oct 2026: the box was down 04:04-10:45, the daily 08:45 brief (plain cron) was
simply re-armed for the next day at restart, and nothing anywhere said it had been skipped.
"""

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta

from reminders_cli import commands, db
from reminders_cli.config import Config
from reminders_cli.scheduler import create_scheduler


def _set_scheduled(config: Config, reminder_id: str, when: datetime):
    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute("UPDATE reminders SET scheduled_time = ? WHERE id = ?", (when.isoformat(), reminder_id))
        conn.commit()


def _scheduled(config: Config, reminder_id: str) -> datetime:
    with closing(db.get_db(config.data_dir)) as conn:
        row = conn.execute("SELECT scheduled_time FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    return db.parse_datetime(row["scheduled_time"])


def _missed(notif_dir):
    return [json.loads(p.read_text()) for p in notif_dir.glob("*-reminders-reminder_missed.json")]


def test_cron_fire_missed_during_downtime_is_reported_once(tmp_config, tmp_path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    brief = commands.remind_set(tmp_config, commands.ReminderSpec(message="Morning brief.", cron="45 8 * * *", tz="Europe/London"))
    other = commands.remind_set(tmp_config, commands.ReminderSpec(message="not due", cron="0 11 * * *", tz="Europe/London"))

    # positive: the brief's next fire sits two hours in the past, as after an outage
    _set_scheduled(tmp_config, brief["id"], datetime.now(UTC) - timedelta(hours=2))
    commands.restore_all_jobs(tmp_config, create_scheduler(), notif_dir=notif_dir)
    missed = _missed(notif_dir)
    assert len(missed) == 1
    assert missed[0]["reminder_id"] == brief["id"]
    assert missed[0]["message"].startswith("[MISSED: ") and "Morning brief." in missed[0]["message"]
    assert _scheduled(tmp_config, brief["id"]) > datetime.now(UTC)

    # negative: a second restart reports nothing new, and the not-due row never reported
    commands.restore_all_jobs(tmp_config, create_scheduler(), notif_dir=notif_dir)
    assert len(_missed(notif_dir)) == 1
    assert all(m["reminder_id"] != other["id"] for m in _missed(notif_dir))


def test_cron_fire_inside_grace_is_not_reported(tmp_config, tmp_path):
    """A fire seconds ago is probably mid-flight, never a miss."""
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    r = commands.remind_set(tmp_config, commands.ReminderSpec(message="racing", cron="* * * * *"))
    _set_scheduled(tmp_config, r["id"], datetime.now(UTC) - timedelta(seconds=5))
    commands.restore_all_jobs(tmp_config, create_scheduler(), notif_dir=notif_dir)
    assert _missed(notif_dir) == []
