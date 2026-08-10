"""The native-task-tool surface: the `completed` alias, the `in_progress` open status, and that
adding it never strands a task's reminders. CLI-level aliases (`create`, `--subject`) live in
test_e2e.py alongside the other subprocess tests."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from tasks_cli import commands, db


def _auto_reminder_count(config, task_id: str) -> int:
    with closing(db.get_db(config.data_dir)) as conn:
        return conn.execute("SELECT COUNT(*) FROM reminders WHERE task_id = ? AND auto_generated = 1", (task_id,)).fetchone()[0]


def test_completed_maps_to_done(tmp_config):
    task = commands.add_task(tmp_config, title="finish")
    result = commands.update_task(tmp_config, task_id=task["id"], status="completed")
    assert result["status"] == "done"
    assert result["completed_at"] is not None


def test_invalid_status_rejected(tmp_config):
    task = commands.add_task(tmp_config, title="x")
    with pytest.raises(ValueError):
        commands.update_task(tmp_config, task_id=task["id"], status="bogus")


def test_in_progress_stays_open_in_list_and_digest(tmp_config):
    overdue = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    task = commands.add_task(tmp_config, title="overdue wip", due=commands.DueSpec(due_datetime=overdue, timezone="UTC"))
    commands.update_task(tmp_config, task_id=task["id"], status="in_progress")
    assert any(t["id"] == task["id"] for t in commands.list_tasks(tmp_config))
    digest = commands.build_digest(tmp_config)
    assert digest is not None
    assert task["id"] in digest


def test_open_status_toggle_never_duplicates_reminders(tmp_config):
    due = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    task = commands.add_task(tmp_config, title="wip", due=commands.DueSpec(due_datetime=due, timezone="UTC"))
    baseline = _auto_reminder_count(tmp_config, task["id"])
    assert baseline > 0
    commands.update_task(tmp_config, task_id=task["id"], status="in_progress")
    assert _auto_reminder_count(tmp_config, task["id"]) == baseline


def test_reopen_from_done_via_in_progress_rebuilds_reminders(tmp_config):
    due = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    task = commands.add_task(tmp_config, title="reopen", due=commands.DueSpec(due_datetime=due, timezone="UTC"))
    commands.update_task(tmp_config, task_id=task["id"], status="done")
    assert _auto_reminder_count(tmp_config, task["id"]) == 0
    reopened = commands.update_task(tmp_config, task_id=task["id"], status="in_progress")
    assert reopened["status"] == "in_progress"
    assert reopened["completed_at"] is None
    assert _auto_reminder_count(tmp_config, task["id"]) > 0


def test_migration_v5_to_v6_widens_status_check(tmp_path):
    data_dir = tmp_path / "old"
    data_dir.mkdir()
    conn = sqlite3.connect(data_dir / "tasks.db")
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version (version) VALUES (5)")
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),"
        " priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)), due_date TEXT,"
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT,"
        " backburner INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute("INSERT INTO tasks (id, title) VALUES ('t1', 'kept')")
    conn.commit()
    conn.close()

    db.init_db(data_dir)

    with closing(sqlite3.connect(data_dir / "tasks.db")) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute("SELECT title FROM tasks WHERE id = 't1'").fetchone()[0] == "kept"
        # The old CHECK would reject this; after v6 it is allowed.
        conn.execute("UPDATE tasks SET status = 'in_progress' WHERE id = 't1'")
        conn.commit()
