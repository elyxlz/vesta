"""Unit tests for the overdue pressure loop: adaptive reminder ladder, at-due decision fire,
postpone/snooze verbs, the daily digest, and overdue ordering."""

import json
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tasks_cli import commands, db
from tasks_cli.config import Config
from tasks_cli.scheduler import create_scheduler


def _auto_reminders(config: Config, task_id: str) -> list[dict]:
    with closing(db.get_db(config.data_dir)) as conn:
        rows = conn.execute("SELECT * FROM reminders WHERE task_id = ? AND auto_generated = 1", (task_id,)).fetchall()
    return [dict(row) for row in rows]


def _add_task_due_in(config: Config, title: str, delta: timedelta) -> dict:
    due = (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%S")
    return commands.add_task(config, title=title, due_datetime=due, timezone="UTC")


def _force_due_date(config: Config, task_id: str, due: datetime):
    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (due.isoformat(), task_id))
        conn.commit()


def _force_created_at(config: Config, task_id: str, created: datetime):
    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (created.strftime("%Y-%m-%d %H:%M:%S"), task_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Adaptive auto-reminder ladder
# ---------------------------------------------------------------------------


def test_far_future_due_gets_halving_checkpoints(tmp_config: Config):
    task = _add_task_due_in(tmp_config, "far future", timedelta(days=180))
    schedules = {r["schedule_type"] for r in _auto_reminders(tmp_config, task["id"])}
    assert schedules == {
        "auto: about 3 months before due",
        "auto: about 6 weeks before due",
        "auto: about 3 weeks before due",
        "auto: 1 week before due",
        "auto: 1 day before due",
        "auto: 1 hour before due",
        "auto: 15 minutes before due",
        "auto: at due",
    }


def test_near_due_has_no_checkpoints_and_skips_past_rungs(tmp_config: Config):
    task = _add_task_due_in(tmp_config, "near", timedelta(days=3))
    schedules = {r["schedule_type"] for r in _auto_reminders(tmp_config, task["id"])}
    assert schedules == {
        "auto: 1 day before due",
        "auto: 1 hour before due",
        "auto: 15 minutes before due",
        "auto: at due",
    }


def test_at_due_reminder_fires_at_due_time_with_decision_menu(tmp_config: Config):
    task = _add_task_due_in(tmp_config, "decide", timedelta(days=3))
    at_due = [r for r in _auto_reminders(tmp_config, task["id"]) if r["schedule_type"] == "auto: at due"]
    assert len(at_due) == 1
    assert db.parse_datetime(at_due[0]["scheduled_time"]) == db.parse_datetime(commands.get_task(tmp_config, task_id=task["id"])["due_date"])
    for command in (f"tasks done {task['id']}", f"tasks postpone {task['id']}", f"tasks delete {task['id']}"):
        assert command in at_due[0]["message"]


# ---------------------------------------------------------------------------
# Postpone
# ---------------------------------------------------------------------------


def test_postpone_overdue_task_moves_due_forward_and_rebuilds_reminders(tmp_config: Config):
    task = _add_task_due_in(tmp_config, "late", timedelta(minutes=30))
    _force_due_date(tmp_config, task["id"], datetime.now(UTC) - timedelta(days=3))

    updated = commands.postpone_task(tmp_config, task_id=task["id"], in_days=2)

    assert db.parse_datetime(updated["due_date"]) > datetime.now(UTC) + timedelta(days=1)
    schedules = {r["schedule_type"] for r in _auto_reminders(tmp_config, task["id"])}
    assert "auto: at due" in schedules


def test_postpone_gives_undated_task_a_due_date(tmp_config: Config):
    task = commands.add_task(tmp_config, title="undated")
    updated = commands.postpone_task(tmp_config, task_id=task["id"], in_hours=6)
    assert updated["due_date"] is not None
    assert {r["schedule_type"] for r in _auto_reminders(tmp_config, task["id"])} == {
        "auto: 1 hour before due",
        "auto: 15 minutes before due",
        "auto: at due",
    }


def test_postpone_requires_timing(tmp_config: Config):
    task = commands.add_task(tmp_config, title="no timing")
    with pytest.raises(ValueError, match="Say when"):
        commands.postpone_task(tmp_config, task_id=task["id"])


# ---------------------------------------------------------------------------
# Reminder snooze
# ---------------------------------------------------------------------------


def test_snooze_moves_a_pending_one_shot(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, message="one shot", in_hours=1)
    result = commands.remind_snooze(tmp_config, reminder_id=reminder["id"], in_hours=4)

    new_run = db.parse_datetime(result["next_run"])
    assert new_run > datetime.now(UTC) + timedelta(hours=3)
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        row = conn.execute("SELECT completed, trigger_data FROM reminders WHERE id = ?", (reminder["id"],)).fetchone()
    assert row["completed"] == 0
    assert db.parse_datetime(json.loads(row["trigger_data"])["run_date"]) == new_run


def test_snooze_reactivates_a_fired_reminder(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, message="already fired", in_hours=1)
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        conn.execute("UPDATE reminders SET completed = 1 WHERE id = ?", (reminder["id"],))
        conn.commit()

    commands.remind_snooze(tmp_config, reminder_id=reminder["id"], in_minutes=30)

    with closing(db.get_db(tmp_config.data_dir)) as conn:
        row = conn.execute("SELECT completed FROM reminders WHERE id = ?", (reminder["id"],)).fetchone()
    assert row["completed"] == 0


def test_snooze_rejects_recurring(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, message="daily", scheduled_datetime="2026-04-26T10:30:00", tz="UTC", recurring="daily")
    with pytest.raises(ValueError, match="one-shot"):
        commands.remind_snooze(tmp_config, reminder_id=reminder["id"], in_hours=1)


def test_snooze_requires_timing(tmp_config: Config):
    reminder = commands.remind_set(tmp_config, message="one shot", in_hours=1)
    with pytest.raises(ValueError, match="Say when"):
        commands.remind_snooze(tmp_config, reminder_id=reminder["id"])


def test_stale_fire_after_snooze_is_skipped_not_completed(tmp_config: Config, tmp_path: Path):
    """A job armed before a snooze must not fire against the snoozed row (the snooze-race guard)."""
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    reminder = commands.remind_set(tmp_config, message="imminent", in_minutes=1)
    commands.remind_snooze(tmp_config, reminder_id=reminder["id"], in_hours=4)

    commands.send_reminder_job(reminder["id"], message="imminent", data_dir=str(tmp_config.data_dir), notif_dir=str(notif_dir))

    assert list(notif_dir.glob("*.json")) == []
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        assert conn.execute("SELECT completed FROM reminders WHERE id = ?", (reminder["id"],)).fetchone()["completed"] == 0


def test_just_fired_one_shot_is_not_replayed_as_missed(tmp_config: Config, tmp_path: Path):
    """Restore must not declare a seconds-old one-shot missed (it is likely mid-fire), but a
    genuinely stale one still replays."""
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    scheduler = create_scheduler()
    reminder = commands.remind_set(tmp_config, message="racing", in_minutes=1)

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
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        assert conn.execute("SELECT completed FROM reminders WHERE id = ?", (reminder["id"],)).fetchone()["completed"] == 0

    rewind_run_date(120)
    commands.restore_jobs_by_ids(tmp_config, scheduler, {reminder["id"]}, notif_dir=notif_dir)
    missed = list(notif_dir.glob("*-tasks-reminder.json"))
    assert len(missed) == 1
    assert json.loads(missed[0].read_text())["missed"] is True
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        assert conn.execute("SELECT completed FROM reminders WHERE id = ?", (reminder["id"],)).fetchone()["completed"] == 1


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


def test_digest_lists_overdue_and_stale_with_commands(tmp_config: Config):
    overdue = _add_task_due_in(tmp_config, "overdue task", timedelta(minutes=30))
    _force_due_date(tmp_config, overdue["id"], datetime.now(UTC) - timedelta(days=2))
    stale = commands.add_task(tmp_config, title="stale task")
    _force_created_at(tmp_config, stale["id"], datetime.now(UTC) - timedelta(days=20))
    fresh = commands.add_task(tmp_config, title="fresh task")

    message = commands.build_digest(tmp_config)

    assert message is not None
    assert overdue["id"] in message and "overdue 2d" in message
    assert stale["id"] in message and "created 3w ago" in message
    assert fresh["id"] not in message
    for command in ("tasks done <id>", "tasks postpone <id> --in-days N", "tasks delete <id>"):
        assert command in message


def test_digest_is_none_when_nothing_needs_attention(tmp_config: Config):
    commands.add_task(tmp_config, title="fresh")
    _add_task_due_in(tmp_config, "future", timedelta(days=3))
    assert commands.build_digest(tmp_config) is None


def test_digest_emits_at_most_once_per_day(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    overdue = _add_task_due_in(tmp_config, "still overdue", timedelta(minutes=30))
    _force_due_date(tmp_config, overdue["id"], datetime.now(UTC) - timedelta(days=1))

    now = datetime.now(UTC)
    assert commands.maybe_send_digest(tmp_config, notif_dir, now=now) is True
    assert commands.maybe_send_digest(tmp_config, notif_dir, now=now + timedelta(hours=6)) is False
    assert commands.maybe_send_digest(tmp_config, notif_dir, now=now + timedelta(hours=24)) is True

    files = list(notif_dir.glob("*-tasks-task_digest.json"))
    assert len(files) == 2
    payload = json.loads(files[0].read_text())
    assert payload["type"] == "task_digest"
    assert overdue["id"] in payload["message"]


def test_digest_skips_quietly_when_clean_and_does_not_stamp(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifications"
    notif_dir.mkdir()
    assert commands.maybe_send_digest(tmp_config, notif_dir) is False
    assert list(notif_dir.glob("*.json")) == []
    # Nothing stamped: the moment something goes overdue, the next check emits immediately.
    overdue = _add_task_due_in(tmp_config, "now overdue", timedelta(minutes=30))
    _force_due_date(tmp_config, overdue["id"], datetime.now(UTC) - timedelta(hours=1))
    assert commands.maybe_send_digest(tmp_config, notif_dir) is True


# ---------------------------------------------------------------------------
# Overdue ordering + migration
# ---------------------------------------------------------------------------


def test_overdue_today_floats_to_top(tmp_config: Config):
    high = _add_task_due_in(tmp_config, "high future", timedelta(days=1))
    commands.update_task(tmp_config, task_id=high["id"], priority=3)
    overdue = _add_task_due_in(tmp_config, "overdue an hour ago", timedelta(minutes=30))
    _force_due_date(tmp_config, overdue["id"], datetime.now(UTC) - timedelta(hours=1))

    listed = commands.list_tasks(tmp_config)
    assert listed[0]["id"] == overdue["id"]


def test_migration_v4_regenerates_auto_reminders_and_creates_meta(tmp_config: Config):
    task = _add_task_due_in(tmp_config, "legacy task", timedelta(days=5))
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        # Rewind to a v3-shaped db: no meta table, no at-due reminder.
        conn.execute("DELETE FROM reminders WHERE schedule_type = 'auto: at due'")
        conn.execute("DROP TABLE meta")
        conn.execute("UPDATE schema_version SET version = 3")
        conn.commit()

    db.init_db(tmp_config.data_dir)

    schedules = {r["schedule_type"] for r in _auto_reminders(tmp_config, task["id"])}
    assert "auto: at due" in schedules
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 4
        assert db.get_meta(conn, "anything") is None
