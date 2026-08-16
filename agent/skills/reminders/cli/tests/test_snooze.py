"""Snooze semantics and the two fire-time race guards: a stale armed job never fires against a
snoozed row (STALE_FIRE_SLACK), and restore never replays a seconds-old one-shot as missed
(MISSED_GRACE)."""

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from reminders_cli import commands, db
from reminders_cli import format as fmt
from reminders_cli.config import Config
from reminders_cli.scheduler import create_scheduler


def _row(config: Config, reminder_id: str):
    with closing(db.get_db(config.data_dir)) as conn:
        return conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()


def test_snooze_moves_a_pending_one_shot(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="one shot", in_hours=1))
    result = commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_hours=4))

    new_run = db.parse_datetime(result["next_run"])
    assert new_run > datetime.now(UTC) + timedelta(hours=3)
    row = _row(tmp_config, reminder["id"])
    assert row["completed"] == 0
    assert db.parse_datetime(json.loads(row["trigger_data"])["run_date"]) == new_run


def test_snooze_reactivates_a_fired_reminder(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="already fired", in_hours=1))
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder["id"],))
        conn.commit()

    commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_minutes=30))

    assert _row(tmp_config, reminder["id"])["completed"] == 0


def test_snooze_relabels_the_schedule_shown_by_list(tmp_config: Config):
    """The schedule label is what `reminders list` prints beside each row, so a stale one makes a
    still-pending reminder look like it already fired."""
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="chase it", scheduled_datetime="2026-07-19T09:00:00", tz="UTC"))
    assert reminder["schedule"] == "once at 2026-07-19T09:00:00+00:00"

    result = commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_days=8))
    new_run = db.parse_datetime(result["next_run"])

    listed = next(r for r in commands.remind_list(tmp_config) if r["id"] == reminder["id"])
    assert db.parse_datetime(listed["next_run"]) == new_run
    assert db.parse_datetime(listed["schedule"].removeprefix("once at ")) == new_run

    rendered = fmt.format_reminder_list([listed])
    assert "2026-07-19" not in rendered
    assert rendered.startswith("in 8d\t")


def test_snooze_fire_time_is_second_precision(tmp_config: Config):
    """A relative snooze derives its fire time from now, so it must not leak sub-second precision."""
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="chase it", in_hours=1))

    result = commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_hours=5))

    assert db.parse_datetime(result["next_run"]).microsecond == 0
    assert "." not in result["schedule"], f"snooze fire time leaked sub-second precision: {result['schedule']}"


def test_snooze_rejects_recurring(tmp_config: Config):
    reminder = commands.remind_set(
        tmp_config, commands.ReminderSpec(message="daily", scheduled_datetime="2026-04-26T10:30:00", tz="UTC", recurring="daily")
    )
    with pytest.raises(ValueError, match="one-shot"):
        commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_hours=1))


def test_snooze_requires_timing(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="one shot", in_hours=1))
    with pytest.raises(ValueError, match="Say when"):
        commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec())


def test_stale_fire_after_snooze_is_skipped_not_completed(tmp_config: Config, tmp_path: Path):
    """A job armed before a snooze must not fire against the snoozed row."""
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="imminent", in_minutes=1))
    commands.remind_snooze(tmp_config, reminder_id=reminder["id"], spec=commands.SnoozeSpec(in_hours=4))

    commands.send_reminder_job(reminder["id"], message="imminent", data_dir=str(tmp_config.data_dir), notif_dir=str(notif_dir))

    assert list(notif_dir.glob("*.json")) == []
    assert _row(tmp_config, reminder["id"])["completed"] == 0


def test_just_fired_one_shot_is_not_replayed_as_missed(tmp_config: Config, tmp_path: Path):
    """Restore must not declare a seconds-old one-shot missed (it is likely mid-fire), but a
    genuinely stale one still replays."""
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    scheduler = create_scheduler()
    reminder = commands.remind_set(tmp_config, commands.ReminderSpec(message="racing", in_minutes=1))

    def rewind_run_date(seconds_ago: int):
        run_date = (datetime.now(UTC) - timedelta(seconds=seconds_ago)).isoformat()
        with closing(db.get_db(tmp_config.data_dir)) as conn:
            conn.execute(
                "UPDATE reminders SET trigger_data = ?, scheduled_time = ? WHERE id = ?",
                (json.dumps({"type": "date", "run_date": run_date}), run_date, reminder["id"]),
            )
            conn.commit()

    rewind_run_date(5)
    commands.restore_jobs_by_ids(tmp_config, scheduler, {reminder["id"]}, notif_dir=notif_dir)
    assert list(notif_dir.glob("*.json")) == []
    assert _row(tmp_config, reminder["id"])["completed"] == 0

    rewind_run_date(120)
    commands.restore_jobs_by_ids(tmp_config, scheduler, {reminder["id"]}, notif_dir=notif_dir)
    missed = list(notif_dir.glob("*-reminders-reminder.json"))
    assert len(missed) == 1
    assert json.loads(missed[0].read_text())["missed"] is True
    assert _row(tmp_config, reminder["id"])["completed"] == 1
