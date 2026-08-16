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


def _make_legacy_db(home: pathlib.Path) -> None:
    legacy = home / ".tasks"
    legacy.mkdir(parents=True)
    conn = sqlite3.connect(legacy / "tasks.db")
    conn.execute(
        "CREATE TABLE reminders (id TEXT PRIMARY KEY, task_id TEXT, message TEXT, schedule_type TEXT,"
        " scheduled_time TEXT, completed INTEGER, created_at TEXT, trigger_data TEXT)"
    )
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
