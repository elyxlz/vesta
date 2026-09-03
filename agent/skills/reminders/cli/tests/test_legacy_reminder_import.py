"""The one-off import from the legacy unified tasks store must only ever seed the real store.

The legacy database lives at an absolute, home-relative path (`~/.tasks/tasks.db`) while the
database being initialised is whatever the caller passed. Without a guard tying the two together,
every freshly created reminders database, including the temp-directory ones the test suite builds,
would be seeded from a store that is not its own: a brand new database coming up holding reminders
belonging to a different store. That reads as a hermetic fixture and is not one.

CI never sees the mistake, because a clean runner has no legacy database to import. The suite is
green for the wrong reason, which is the only kind of green worth writing a test about.
"""

import pathlib
import sqlite3

from reminders_cli import db

# id, task_id (dropped on import), message, schedule_type, scheduled_time, completed, created_at, trigger_data
LEGACY_ROW = (
    "leg00001",
    "t1",
    "a reminder from the old CLI",
    "once",
    "2026-01-01T09:00:00+00:00",
    0,
    "2026-01-01T00:00:00+00:00",
    None,
)


# A materialized pre-due rung, as the tasks store built them before checkpoints were computed.
AUTO_ROW = ("auto0001", "t1", "Task due in 1 day: file taxes", "auto: 1 day before due", "2026-01-02T09:00:00+00:00", 0, "2026-01-01", None)


def _make_legacy_db(home: pathlib.Path, *, with_auto_column: bool = False) -> None:
    """A tasks store holding LEGACY_ROW; `with_auto_column` gives it the v7 shape (the
    auto_generated column present) plus one materialized rung."""
    legacy = home / ".tasks"
    legacy.mkdir(parents=True)
    conn = sqlite3.connect(legacy / "tasks.db")
    auto_column = ", auto_generated INTEGER" if with_auto_column else ""
    conn.execute(
        "CREATE TABLE reminders (id TEXT PRIMARY KEY, task_id TEXT, message TEXT, schedule_type TEXT,"
        f" scheduled_time TEXT, completed INTEGER, created_at TEXT, trigger_data TEXT{auto_column})"
    )
    if with_auto_column:
        conn.execute("INSERT INTO reminders VALUES (?,?,?,?,?,?,?,?,0)", LEGACY_ROW)
        conn.execute("INSERT INTO reminders VALUES (?,?,?,?,?,?,?,?,1)", AUTO_ROW)
    else:
        conn.execute("INSERT INTO reminders VALUES (?,?,?,?,?,?,?,?)", LEGACY_ROW)
    conn.commit()
    conn.close()


def _reminder_count(data_dir: pathlib.Path) -> int:
    conn = sqlite3.connect(data_dir / "reminders.db")
    try:
        return conn.execute("SELECT count(*) FROM reminders").fetchone()[0]
    finally:
        conn.close()


def test_a_database_outside_the_real_store_is_never_seeded(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    _make_legacy_db(home)

    elsewhere = tmp_path / "scratch/reminders"
    elsewhere.mkdir(parents=True)
    db.init_db(elsewhere)

    assert _reminder_count(elsewhere) == 0


def test_the_real_store_gets_the_one_off_import_once(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    _make_legacy_db(home)

    real = home / ".reminders"
    real.mkdir()
    db.init_db(real)
    assert _reminder_count(real) == 1

    # The marker makes a second init a no-op, so re-running never double-imports.
    db.init_db(real)
    assert _reminder_count(real) == 1


def test_imported_row_drops_the_task_link(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    _make_legacy_db(home)

    real = home / ".reminders"
    real.mkdir()
    db.init_db(real)

    conn = sqlite3.connect(real / "reminders.db")
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
        assert "task_id" not in columns
        message = conn.execute("SELECT message FROM reminders WHERE id = 'leg00001'").fetchone()[0]
        assert message == "a reminder from the old CLI"
    finally:
        conn.close()


def test_materialized_task_checkpoints_are_not_imported(tmp_path, monkeypatch):
    """The tasks daemon computes its own checkpoints; importing the old rung rows would fire each one twice."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    _make_legacy_db(home, with_auto_column=True)

    real = home / ".reminders"
    real.mkdir()
    db.init_db(real)

    conn = sqlite3.connect(real / "reminders.db")
    try:
        ids = {row[0] for row in conn.execute("SELECT id FROM reminders")}
    finally:
        conn.close()
    assert ids == {"leg00001"}


def test_the_legacy_table_is_dropped_after_import(tmp_path, monkeypatch):
    """Once copied, the source `reminders` table is dropped so the tasks store keeps no dead table."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    _make_legacy_db(home)

    db.default_data_dir().mkdir()
    db.init_db(db.default_data_dir())
    assert _reminder_count(db.default_data_dir()) == 1

    conn = sqlite3.connect(home / ".tasks" / "tasks.db")
    try:
        row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'reminders'").fetchone()
    finally:
        conn.close()
    assert row is None


def test_a_failed_read_leaves_the_import_to_retry(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    legacy = home / ".tasks"
    legacy.mkdir(parents=True)
    (legacy / "tasks.db").write_text("not a database")

    real = home / ".reminders"
    real.mkdir()
    db.init_db(real)
    assert _reminder_count(real) == 0

    # The store heals; the next init imports because no marker was set on the failure.
    (legacy / "tasks.db").unlink()
    legacy.rmdir()
    _make_legacy_db(home)
    db.init_db(real)
    assert _reminder_count(real) == 1
