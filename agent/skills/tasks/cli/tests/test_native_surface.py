"""The native-task-tool surface: closing with `completed`, the `in_progress` open status, and that
adding it never strands a task's reminders. CLI-level spellings (`create`, `--subject`) live in
test_e2e.py alongside the other subprocess tests."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta

import pytest
from tasks_cli import commands, db


def _auto_reminder_count(config, task_id: str) -> int:
    with closing(db.get_db(config.data_dir)) as conn:
        return conn.execute("SELECT COUNT(*) FROM reminders WHERE task_id = ? AND auto_generated = 1", (task_id,)).fetchone()[0]


def test_completed_closes_a_task(tmp_config):
    task = commands.add_task(tmp_config, subject="finish")
    result = commands.update_task(tmp_config, task_id=task["id"], status="completed")
    assert result["status"] == "completed"
    assert result["completed_at"] is not None


def test_invalid_status_rejected(tmp_config):
    task = commands.add_task(tmp_config, subject="x")
    with pytest.raises(ValueError):
        commands.update_task(tmp_config, task_id=task["id"], status="bogus")


def test_in_progress_stays_open_in_list_and_digest(tmp_config):
    overdue = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    task = commands.add_task(tmp_config, subject="overdue wip", due=commands.DueSpec(due_datetime=overdue, timezone="UTC"))
    commands.update_task(tmp_config, task_id=task["id"], status="in_progress")
    assert any(t["id"] == task["id"] for t in commands.list_tasks(tmp_config))
    digest = commands.build_digest(tmp_config)
    assert digest is not None
    assert task["id"] in digest


def test_open_status_toggle_never_duplicates_reminders(tmp_config):
    due = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    task = commands.add_task(tmp_config, subject="wip", due=commands.DueSpec(due_datetime=due, timezone="UTC"))
    baseline = _auto_reminder_count(tmp_config, task["id"])
    assert baseline > 0
    commands.update_task(tmp_config, task_id=task["id"], status="in_progress")
    assert _auto_reminder_count(tmp_config, task["id"]) == baseline


def test_reopen_from_completed_via_in_progress_rebuilds_reminders(tmp_config):
    due = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    task = commands.add_task(tmp_config, subject="reopen", due=commands.DueSpec(due_datetime=due, timezone="UTC"))
    commands.update_task(tmp_config, task_id=task["id"], status="completed")
    assert _auto_reminder_count(tmp_config, task["id"]) == 0
    reopened = commands.update_task(tmp_config, task_id=task["id"], status="in_progress")
    assert reopened["status"] == "in_progress"
    assert reopened["completed_at"] is None
    assert _auto_reminder_count(tmp_config, task["id"]) > 0


def test_migration_v6_to_v7_renames_subject_and_completed(tmp_path):
    data_dir = tmp_path / "old"
    data_dir.mkdir()
    conn = sqlite3.connect(data_dir / "tasks.db")
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version (version) VALUES (6)")
    conn.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'done')),"
        " priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)), due_date TEXT,"
        " created_at TEXT DEFAULT CURRENT_TIMESTAMP, completed_at TEXT,"
        " backburner INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute("INSERT INTO tasks (id, title, status) VALUES ('t1', 'kept', 'done')")
    conn.commit()
    conn.close()

    db.init_db(data_dir)

    with closing(sqlite3.connect(data_dir / "tasks.db")) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION
        # The row survives with its text under the new column name and the renamed status value.
        assert conn.execute("SELECT subject FROM tasks WHERE id = 't1'").fetchone()[0] == "kept"
        assert conn.execute("SELECT status FROM tasks WHERE id = 't1'").fetchone()[0] == "completed"
