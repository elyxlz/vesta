"""Unit tests for computed due-date checkpoints: the ladder shape, the serve-tick engine, and
the v7 -> v8 migration that retired the materialized auto-reminder rows."""

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tasks_cli import commands, db
from tasks_cli.config import Config


def _add_task_due_in(config: Config, subject: str, delta: timedelta) -> dict:
    due = (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%S")
    return commands.add_task(config, subject=subject, due=commands.DueSpec(due_datetime=due, timezone="UTC"))


def _reminder_notifications(notif_dir: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(notif_dir.glob("*.json")) if json.loads(p.read_text())["type"] == "reminder"]


# ---------------------------------------------------------------------------
# Ladder shape
# ---------------------------------------------------------------------------


def test_far_future_due_gets_doubling_checkpoints():
    now = datetime.now(UTC)
    rungs = commands.checkpoint_times(now + timedelta(days=180), now)
    labels = [label for label, _ in rungs]
    assert labels == [
        "about 4 months",
        "about 8 weeks",
        "about 4 weeks",
        "about 2 weeks",
        "1 week",
        "1 day",
        "1 hour",
        "15 minutes",
        None,
    ]
    fire_times = [t for _, t in rungs]
    assert fire_times == sorted(fire_times)


def test_near_due_drops_rungs_before_creation():
    now = datetime.now(UTC)
    rungs = commands.checkpoint_times(now + timedelta(days=3), now)
    assert [label for label, _ in rungs] == ["1 day", "1 hour", "15 minutes", None]


def test_two_computations_of_the_same_ladder_agree():
    """Anchor-free is the design invariant: the ladder derives from (due, created) alone, so a
    recomputation after any amount of downtime lands on the identical rungs."""
    created = datetime(2026, 1, 1, tzinfo=UTC)
    due = datetime(2026, 6, 1, tzinfo=UTC)
    assert commands.checkpoint_times(due, created) == commands.checkpoint_times(due, created)


# ---------------------------------------------------------------------------
# Firing engine
# ---------------------------------------------------------------------------


def test_lead_checkpoint_fires_once_and_advances_the_marker(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "ship it", timedelta(hours=2))

    later = datetime.now(UTC) + timedelta(hours=1, minutes=1)
    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=later) == 1
    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=later) == 0

    notifs = _reminder_notifications(notif_dir)
    assert len(notifs) == 1
    assert "Task due in 1 hour: ship it" in notifs[0]["message"]
    assert notifs[0]["task_id"] == task["id"]


def test_creating_a_task_fires_no_rung_that_lands_at_creation(tmp_config: Config, tmp_path: Path):
    """--in-days 1 puts the due-1d rung at the creation instant; created_at is second-truncated,
    so without the marker that rung reads as already passed and fires on the first tick."""
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    commands.add_task(tmp_config, subject="fresh", due=commands.DueSpec(due_in_days=1))

    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(seconds=2)) == 0


def test_at_due_fires_the_decision_menu(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "decide", timedelta(seconds=1))

    fired = commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(minutes=1))
    assert fired == 1
    message = _reminder_notifications(notif_dir)[0]["message"]
    for command in (f"tasks done {task['id']}", f"tasks postpone {task['id']}", f"tasks delete {task['id']}"):
        assert command in message


def test_downtime_collapses_to_one_catch_up_fire(tmp_config: Config, tmp_path: Path):
    """A week offline must yield the newest missed rung once, not a backlog of every rung."""
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    _add_task_due_in(tmp_config, "buried", timedelta(seconds=1))

    fired = commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(days=7))
    assert fired == 1
    assert len(_reminder_notifications(notif_dir)) == 1


def test_postpone_rearms_the_ladder(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "moving target", timedelta(seconds=1))
    commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(minutes=1))

    commands.postpone_task(tmp_config, task_id=task["id"], due=commands.DueSpec(due_in_days=2))

    later = datetime.now(UTC) + timedelta(days=1, hours=1)
    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=later) == 1
    assert "Task due in 1 day" in _reminder_notifications(notif_dir)[-1]["message"]


def test_dating_an_old_task_does_not_fire_rungs_the_date_put_in_the_past(tmp_config: Config, tmp_path: Path):
    """A task created a month ago and postponed to three days out has its due-1w rung in the past;
    that rung could never have fired, so it must not fire now as a mislabelled catch-up."""
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = commands.add_task(tmp_config, subject="old undated")
    with closing(db.get_db(tmp_config.data_dir)) as conn:
        month_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        conn.execute("UPDATE tasks SET created_at = ? WHERE id = ?", (month_ago, task["id"]))
        conn.commit()

    commands.postpone_task(tmp_config, task_id=task["id"], due=commands.DueSpec(due_in_days=3))

    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC)) == 0
    two_days_on = datetime.now(UTC) + timedelta(days=2, minutes=1)
    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=two_days_on) == 1
    assert "Task due in 1 day" in _reminder_notifications(notif_dir)[-1]["message"]


def test_retitle_fires_with_the_new_subject(tmp_config: Config, tmp_path: Path):
    """Messages are built at fire time from the current subject, so a retitle needs no machinery."""
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "old name", timedelta(hours=2))
    commands.update_task(tmp_config, task_id=task["id"], subject="new name")

    commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(hours=1, minutes=1))
    assert "new name" in _reminder_notifications(notif_dir)[0]["message"]


def test_completed_task_fires_nothing(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "done early", timedelta(hours=2))
    commands.update_task(tmp_config, task_id=task["id"], status="completed")

    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(days=7)) == 0


def test_parked_task_fires_nothing(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "parked", timedelta(hours=2))
    commands.update_task(tmp_config, task_id=task["id"], backburner=True)

    assert commands.get_task(tmp_config, task_id=task["id"])["due_date"] is None
    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(days=7)) == 0


def test_reopening_resumes_the_ladder(tmp_config: Config, tmp_path: Path):
    notif_dir = tmp_path / "notifs"
    notif_dir.mkdir()
    task = _add_task_due_in(tmp_config, "back again", timedelta(hours=2))
    commands.update_task(tmp_config, task_id=task["id"], status="completed")
    commands.update_task(tmp_config, task_id=task["id"], status="pending")

    assert commands.fire_due_checkpoints(tmp_config, notif_dir, now=datetime.now(UTC) + timedelta(hours=1, minutes=1)) == 1


# ---------------------------------------------------------------------------
# v7 -> v8 migration
# ---------------------------------------------------------------------------


def _build_v7_db(data_dir: Path) -> None:
    conn = sqlite3.connect(data_dir / "tasks.db")
    conn.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO schema_version (version) VALUES (7)")
    conn.execute("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            subject TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'completed')),
            priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
            due_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            backburner INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE reminders (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            message TEXT NOT NULL,
            schedule_type TEXT,
            scheduled_time TEXT,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            trigger_data TEXT,
            auto_generated INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    due = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    conn.execute("INSERT INTO tasks (id, subject, due_date) VALUES ('t1', 'dated', ?)", (due,))
    conn.execute("INSERT INTO tasks (id, subject) VALUES ('t2', 'undated')")
    trigger = json.dumps({"type": "date", "run_date": due})
    conn.execute(
        "INSERT INTO reminders (id, task_id, message, schedule_type, scheduled_time, trigger_data, auto_generated)"
        " VALUES ('auto1', 't1', 'Task due in 1 day: dated', 'auto: 1 day before due', ?, ?, 1)",
        (due, trigger),
    )
    conn.execute(
        "INSERT INTO reminders (id, task_id, message, schedule_type, scheduled_time, trigger_data, auto_generated)"
        " VALUES ('owned1', 't1', 'my own checkpoint', 'once at x', ?, ?, 0)",
        (due, trigger),
    )
    conn.commit()
    conn.close()


def test_v8_deletes_auto_rows_and_keeps_owned_ones(tmp_path: Path):
    data_dir = tmp_path / "tasks"
    data_dir.mkdir()
    _build_v7_db(data_dir)

    db.init_db(data_dir)

    with closing(db.get_db(data_dir)) as conn:
        ids = {row["id"] for row in conn.execute("SELECT id FROM reminders")}
        assert ids == {"owned1"}
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
        assert "auto_generated" not in columns


def test_v8_marks_dated_tasks_fired_through_now_so_nothing_refires(tmp_path: Path):
    data_dir = tmp_path / "tasks"
    data_dir.mkdir()
    _build_v7_db(data_dir)

    db.init_db(data_dir)

    with closing(db.get_db(data_dir)) as conn:
        dated = conn.execute("SELECT checkpoint_fired_through FROM tasks WHERE id = 't1'").fetchone()
        undated = conn.execute("SELECT checkpoint_fired_through FROM tasks WHERE id = 't2'").fetchone()
    assert dated[0] is not None
    marker = db.parse_datetime(dated[0])
    assert abs((marker - datetime.now(UTC)).total_seconds()) < 60
    assert undated[0] is None
