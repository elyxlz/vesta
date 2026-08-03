"""The one-off import from the old reminder CLI must only ever seed the real store.

The legacy database lives at an absolute, home-relative path while the database being initialised
is whatever the caller passed. Nothing tied the two together, so on any box that still has
`~/.reminder/reminders.db` every freshly created tasks database was seeded from it, including the
temp-directory ones the test suite builds. That reads as a hermetic fixture and is not one: a brand
new database came up holding 40 reminders belonging to a different store.

CI never saw it, because a clean runner has no legacy database to import. The suite was green for
the wrong reason, which is the only kind of green worth writing a test about.
"""

import pathlib
import sqlite3

from tasks_cli import db

LEGACY_ROW = (
    "leg00001",
    None,
    "a reminder from the old CLI",
    "once",
    "2026-01-01T09:00:00+00:00",
    0,
    "2026-01-01T00:00:00+00:00",
    None,
    0,
)


def _make_legacy_db(home: pathlib.Path) -> None:
    legacy = home / ".reminder"
    legacy.mkdir(parents=True)
    conn = sqlite3.connect(legacy / "reminders.db")
    conn.execute(
        "CREATE TABLE reminders (id TEXT PRIMARY KEY, task_id TEXT, message TEXT, schedule_type TEXT,"
        " scheduled_time TEXT, completed INTEGER, created_at TEXT, trigger_data TEXT, auto_generated INTEGER)"
    )
    conn.execute("INSERT INTO reminders VALUES (?,?,?,?,?,?,?,?,?)", LEGACY_ROW)
    conn.commit()
    conn.close()


def _reminder_count(data_dir: pathlib.Path) -> int:
    conn = sqlite3.connect(data_dir / "tasks.db")
    try:
        return conn.execute("SELECT count(*) FROM reminders").fetchone()[0]
    finally:
        conn.close()


def test_a_database_outside_the_real_store_is_never_seeded(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    _make_legacy_db(home)

    elsewhere = tmp_path / "scratch/tasks"
    elsewhere.mkdir(parents=True)
    db.init_db(elsewhere)

    assert _reminder_count(elsewhere) == 0


def test_the_real_store_still_gets_the_one_off_import(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
    _make_legacy_db(home)

    real = home / ".tasks"
    real.mkdir()
    db.init_db(real)

    assert _reminder_count(real) == 1
