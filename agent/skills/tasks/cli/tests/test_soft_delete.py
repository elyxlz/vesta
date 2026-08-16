"""Unit tests for the soft delete: a deleted task keeps its row and metadata, stops firing
checkpoints, drops out of the digest and the default list, yet stays reachable through get."""

import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tasks_cli import commands, db
from tasks_cli.config import Config
from tasks_cli.format import format_task_list


def _add_task_due_in(config: Config, subject: str, delta: timedelta) -> dict:
    due = (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%S")
    return commands.add_task(config, subject=subject, due=commands.DueSpec(due_datetime=due, timezone="UTC"))


def _force_created_at(config: Config, task_id: str, created: datetime):
    with closing(db.get_db(config.data_dir)) as conn:
        conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (created.strftime("%Y-%m-%d %H:%M:%S"), task_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Delete marks the row instead of removing it
# ---------------------------------------------------------------------------


def test_delete_marks_row_and_keeps_metadata(tmp_config: Config):
    task = commands.add_task(tmp_config, subject="keep me", initial_metadata="notes stay")
    meta_path = Path(task["metadata_path"])

    result = commands.delete_task(tmp_config, task_id=task["id"])

    assert result == {"id": task["id"], "status": "deleted", "deleted_at": result["deleted_at"]}
    assert result["deleted_at"]
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        row = conn.execute("SELECT deleted_at FROM tasks WHERE id = ?", (task["id"],)).fetchone()
    assert row is not None
    assert row["deleted_at"] == result["deleted_at"]
    assert meta_path.exists()
    assert meta_path.read_text() == "notes stay"


def test_delete_is_idempotent(tmp_config: Config):
    task = commands.add_task(tmp_config, subject="twice")
    commands.delete_task(tmp_config, task_id=task["id"])
    again = commands.delete_task(tmp_config, task_id=task["id"])
    assert again["status"] == "deleted"


def test_get_returns_a_deleted_task_with_its_deleted_at(tmp_config: Config):
    task = commands.add_task(tmp_config, subject="gettable")
    commands.delete_task(tmp_config, task_id=task["id"])

    got = commands.get_task(tmp_config, task_id=task["id"])

    assert got["id"] == task["id"]
    assert got["deleted_at"]


# ---------------------------------------------------------------------------
# Visibility: hidden by default, shown with show_deleted
# ---------------------------------------------------------------------------


def test_deleted_task_hidden_from_list_shown_with_flag(tmp_config: Config):
    live = commands.add_task(tmp_config, subject="live")
    gone = commands.add_task(tmp_config, subject="gone")
    commands.delete_task(tmp_config, task_id=gone["id"])

    default = {t["id"] for t in commands.list_tasks(tmp_config)}
    assert default == {live["id"]}

    with_deleted = {t["id"] for t in commands.list_tasks(tmp_config, show_deleted=True)}
    assert with_deleted == {live["id"], gone["id"]}


def test_deleted_task_hidden_from_search_shown_with_flag(tmp_config: Config):
    gone = commands.add_task(tmp_config, subject="needle gone")
    commands.delete_task(tmp_config, task_id=gone["id"])

    assert commands.search_tasks(tmp_config, query="needle") == []
    found = commands.search_tasks(tmp_config, query="needle", show_deleted=True)
    assert [t["id"] for t in found] == [gone["id"]]


def test_format_marks_deleted_rows(tmp_config: Config):
    gone = commands.add_task(tmp_config, subject="marked gone")
    commands.delete_task(tmp_config, task_id=gone["id"])
    rendered = format_task_list(commands.list_tasks(tmp_config, show_deleted=True))
    assert "[deleted]" in rendered


# ---------------------------------------------------------------------------
# A deleted task goes silent: no checkpoints, out of the digest
# ---------------------------------------------------------------------------


def test_deleted_task_fires_no_checkpoint(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "silenced", timedelta(hours=2))
    commands.delete_task(tmp_config, task_id=task["id"])

    fired = commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(days=7))
    assert fired == 0


def test_deleted_task_absent_from_digest(tmp_config: Config):
    overdue = _add_task_due_in(tmp_config, "overdue then deleted", timedelta(minutes=30))
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        conn.execute("UPDATE tasks SET due_date = ? WHERE id = ?", ((datetime.now(UTC) - timedelta(days=2)).isoformat(), overdue["id"]))
        conn.commit()
    stale = commands.add_task(tmp_config, subject="stale then deleted")
    _force_created_at(tmp_config, stale["id"], datetime.now(UTC) - timedelta(days=20))

    commands.delete_task(tmp_config, task_id=overdue["id"])
    commands.delete_task(tmp_config, task_id=stale["id"])

    assert commands.build_digest(tmp_config) is None


# ---------------------------------------------------------------------------
# v8 -> v9 migration and fresh-db column
# ---------------------------------------------------------------------------


def _build_v8_db(data_dir: Path) -> None:
    conn = sqlite3.connect(data_dir / "tasks.db")
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version (version) VALUES (8)")
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed')),
            priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
            due_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            backburner INTEGER NOT NULL DEFAULT 0,
            checkpoint_fired_through TEXT
        )
    """)
    conn.execute("INSERT INTO tasks (id, subject) VALUES ('t1', 'predates deleted_at')")
    conn.commit()
    conn.close()


def test_v9_adds_deleted_at_column_starting_null(tmp_path: Path):
    data_dir = tmp_path / "tasks"
    data_dir.mkdir()
    _build_v8_db(data_dir)

    db.init_db(data_dir)

    with closing(db.get_db(data_dir)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == db.SCHEMA_VERSION
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "deleted_at" in columns
        assert conn.execute("SELECT deleted_at FROM tasks WHERE id = 't1'").fetchone()["deleted_at"] is None


def test_fresh_db_has_deleted_at_at_head_schema(tmp_config: Config):
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        assert conn.execute("SELECT version FROM schema_version").fetchone()["version"] == 9
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        assert "deleted_at" in columns
