"""Unit tests for the overdue pressure loop: the postpone verb, the daily digest, overdue
ordering, the backburner flag, and schema migrations. The checkpoint ladder lives in
test_checkpoints.py."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tasks_cli import commands, db
from tasks_cli.config import Config


def _add_task_due_in(config: Config, title: str, delta: timedelta) -> dict:
    due = (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%S")
    return commands.add_task(config, subject=title, due=commands.DueSpec(due_datetime=due, timezone="UTC"))


def _force_due_date(config: Config, task_id: str, due: datetime):
    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute("UPDATE tasks SET due_date = ? WHERE id = ?", (due.isoformat(), task_id))
        conn.commit()


def _force_created_at(config: Config, task_id: str, created: datetime):
    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (created.strftime("%Y-%m-%d %H:%M:%S"), task_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Postpone
# ---------------------------------------------------------------------------


def test_postpone_overdue_task_moves_due_forward(tmp_config: Config):
    task = _add_task_due_in(tmp_config, "late", timedelta(minutes=30))
    _force_due_date(tmp_config, task["id"], datetime.now(UTC) - timedelta(days=3))

    updated = commands.postpone_task(tmp_config, task_id=task["id"], in_days=2)

    assert db.parse_datetime(updated["due_date"]) > datetime.now(UTC) + timedelta(days=1)


def test_postpone_gives_undated_task_a_due_date(tmp_config: Config):
    task = commands.add_task(tmp_config, subject="undated")
    updated = commands.postpone_task(tmp_config, task_id=task["id"], in_hours=6)
    assert updated["due_date"] is not None


def test_postpone_requires_timing(tmp_config: Config):
    task = commands.add_task(tmp_config, subject="no timing")
    with pytest.raises(ValueError, match="Say when"):
        commands.postpone_task(tmp_config, task_id=task["id"])


# ---------------------------------------------------------------------------
# Daily digest
# ---------------------------------------------------------------------------


def test_digest_lists_overdue_and_stale_with_commands(tmp_config: Config):
    overdue = _add_task_due_in(tmp_config, "overdue task", timedelta(minutes=30))
    _force_due_date(tmp_config, overdue["id"], datetime.now(UTC) - timedelta(days=2))
    stale = commands.add_task(tmp_config, subject="stale task")
    _force_created_at(tmp_config, stale["id"], datetime.now(UTC) - timedelta(days=20))
    fresh = commands.add_task(tmp_config, subject="fresh task")

    message = commands.build_digest(tmp_config)

    assert message is not None
    assert overdue["id"] in message and "overdue 2d" in message
    assert stale["id"] in message and "created 3w ago" in message
    assert fresh["id"] not in message
    for command in ("tasks done <id>", "tasks postpone <id> --in-days N", "tasks delete <id>"):
        assert command in message


def test_digest_is_none_when_nothing_needs_attention(tmp_config: Config):
    commands.add_task(tmp_config, subject="fresh")
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


def test_migration_from_v3_reaches_head_schema(tmp_path: Path):
    """A genuine v3-shaped db (the `title` column, no meta table, materialized auto rows) must
    climb every released step to the head schema in one init_db pass."""
    data_dir = tmp_path / "tasks"
    data_dir.mkdir(parents=True)
    due = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    with closing(sqlite3.connect(data_dir / "tasks.db")) as legacy:
        legacy.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        legacy.execute("INSERT INTO schema_version (version) VALUES (3)")
        legacy.execute(
            "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT DEFAULT 'pending', "
            "priority INTEGER DEFAULT 2, due_date TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT)"
        )
        legacy.execute(
            "CREATE TABLE reminders (id TEXT PRIMARY KEY, task_id TEXT, message TEXT NOT NULL, schedule_type TEXT, "
            "scheduled_time TEXT, completed INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, "
            "trigger_data TEXT, auto_generated INTEGER DEFAULT 0)"
        )
        legacy.execute("INSERT INTO tasks (id, title, due_date) VALUES ('legacy1', 'legacy task', ?)", (due,))
        legacy.commit()

    db.init_db(data_dir)

    config = Config(data_dir=data_dir, log_dir=data_dir / "logs")
    assert commands.get_task(config, task_id="legacy1")["subject"] == "legacy task"
    with closing(db.get_db(data_dir)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == db.SCHEMA_VERSION
        assert db.get_meta(conn, "anything") is None
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
        assert "auto_generated" not in columns


# ---------------------------------------------------------------------------
# Backburner: the fourth exit from the stale-task digest
# ---------------------------------------------------------------------------


def test_backburner_task_is_not_listed_as_stale(tmp_config: Config):
    """A task parked on purpose must stop appearing in the digest, while an ordinary undated task
    of the same age still appears. Without the second half this test would pass on a digest that
    had simply stopped reporting stale tasks at all."""
    parked = commands.add_task(tmp_config, subject="parked task")
    ordinary = commands.add_task(tmp_config, subject="ordinary undated task")
    for task in (parked, ordinary):
        _force_created_at(tmp_config, task["id"], datetime.now(UTC) - timedelta(days=20))
    commands.update_task(tmp_config, task_id=parked["id"], backburner=True)

    message = commands.build_digest(tmp_config)

    assert message is not None
    assert ordinary["id"] in message
    assert parked["id"] not in message


def test_backburner_task_still_appears_in_task_list(tmp_config: Config):
    """Parking defers the nag, never the task. A parked task that vanished from `tasks list` would
    be a worse bug than the one this feature fixes."""
    parked = commands.add_task(tmp_config, subject="parked task")
    commands.update_task(tmp_config, task_id=parked["id"], backburner=True)

    listed = commands.list_tasks(tmp_config)

    assert [t["id"] for t in listed] == [parked["id"]]
    assert listed[0]["backburner"] == 1


def test_setting_a_due_date_clears_backburner(tmp_config: Config):
    """Committing to a date is the opposite state to parking, so the flag must not survive it."""
    task = commands.add_task(tmp_config, subject="parked then committed")
    commands.update_task(tmp_config, task_id=task["id"], backburner=True)

    commands.update_task(tmp_config, task_id=task["id"], due=commands.DueSpec(due_in_days=3))

    assert commands.get_task(tmp_config, task_id=task["id"])["backburner"] == 0


def test_clearing_a_due_date_leaves_backburner_alone(tmp_config: Config):
    """--clear-due removes a date; it must not silently park the task as a side effect."""
    task = _add_task_due_in(tmp_config, "dated", timedelta(days=3))

    commands.update_task(tmp_config, task_id=task["id"], due=commands.DueSpec(clear=True))

    assert commands.get_task(tmp_config, task_id=task["id"])["backburner"] == 0


def test_backburner_migration_adds_the_column_to_an_existing_v4_db(tmp_path: Path):
    """Every fleet task predates the column, so the upgrade decides what they all start as.

    init_db runs on every daemon start, so the second run must be a no-op rather than a duplicate
    ALTER. Starting from a real v4 database is what makes this a migration test: rerunning init_db
    on an already-current database never reaches the migration at all.
    """
    data_dir = tmp_path / "tasks"
    data_dir.mkdir(parents=True)
    with closing(sqlite3.connect(data_dir / "tasks.db")) as legacy:
        legacy.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
        legacy.execute("INSERT INTO schema_version (version) VALUES (4)")
        legacy.execute(
            "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT DEFAULT 'pending', "
            "priority INTEGER DEFAULT 2, due_date TEXT, created_at TEXT, completed_at TEXT)"
        )
        legacy.execute(
            "CREATE TABLE reminders (id TEXT PRIMARY KEY, task_id TEXT, message TEXT NOT NULL, schedule_type TEXT,"
            " scheduled_time TEXT, completed INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP,"
            " trigger_data TEXT, auto_generated INTEGER DEFAULT 0)"
        )
        legacy.execute("INSERT INTO tasks (id, title, created_at) VALUES ('old1', 'predates the column', '2020-01-01 00:00:00')")
        legacy.commit()

    db.init_db(data_dir)
    db.init_db(data_dir)

    config = Config(data_dir=data_dir, log_dir=data_dir / "logs")
    assert commands.get_task(config, task_id="old1")["backburner"] == 0, "an existing task starts unparked, so the digest keeps nagging"
    with closing(db.get_db(data_dir)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == db.SCHEMA_VERSION


def test_parking_a_dated_task_drops_the_date(tmp_config: Config):
    """Parked AND deadlined is the contradiction the flag exists to remove.

    A parked task that kept its due date would keep its checkpoint ladder firing while the digest
    had been told to stop nagging about it, which is louder than not parking it at all. Dropping
    the date is all it takes: checkpoints derive from the date.
    """
    task = _add_task_due_in(tmp_config, "driven by someone else", timedelta(days=30))
    assert task["due_date"]

    commands.update_task(tmp_config, task_id=task["id"], backburner=True)

    after = commands.get_task(tmp_config, task_id=task["id"])
    assert after["backburner"] == 1
    assert after["due_date"] is None


def test_setting_a_date_in_the_same_call_wins_over_parking(tmp_config: Config):
    """Committing to a date is the opposite of parking, so the date unparks it.

    Passing both in one call is a contradiction, and leaving it parked AND deadlined is the one
    outcome the flag exists to prevent: the digest goes quiet while the reminder ladder keeps
    firing on the same task.
    """
    task = commands.add_task(tmp_config, subject="undecided")
    commands.update_task(tmp_config, task_id=task["id"], backburner=True)
    assert commands.get_task(tmp_config, task_id=task["id"])["backburner"] == 1

    due = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    commands.update_task(tmp_config, task_id=task["id"], backburner=True, due=commands.DueSpec(due_datetime=due, timezone="UTC"))

    after = commands.get_task(tmp_config, task_id=task["id"])
    assert after["due_date"] is not None
    assert after["backburner"] == 0, "a real due date unparks the task, in the same call or a later one"
