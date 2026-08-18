import logging
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from .config import default_data_dir

logger = logging.getLogger(__name__)

# Head schema version, recorded in meta so a later migration step knows where a store starts.
SCHEMA_VERSION = 1

_SCHEMA_VERSION_KEY = "schema_version"
_LEGACY_IMPORT_KEY = "legacy_import_done"

# Columns copied out of a legacy `~/.tasks/tasks.db` reminders table, dropping its `task_id` link.
_LEGACY_COLUMNS = ("id", "message", "schedule_type", "scheduled_time", "completed", "created_at", "trigger_data")


def get_db(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / "reminders.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def parse_datetime(s: str) -> datetime:
    parsed = datetime.fromisoformat(s)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _has_reminders_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'reminders'").fetchone()
    return row is not None


# LEGACY(remove-when: no fleet box still holds reminders in ~/.tasks/tasks.db): a box created before
# the reminders skill existed keeps its reminders in the tasks store; the one-time import below moves
# them into this store. Delete this function, its call, and test_legacy_reminder_import.py once done.
def _import_legacy_reminders(conn: sqlite3.Connection, data_dir: Path):
    """One-time import of the reminders a box still holds in the tasks store at `~/.tasks/tasks.db`.

    The tasks path is absolute and home-relative while the database being built is whatever the
    caller passed, so the import runs ONLY for the real store; without this guard every new database
    (a temp-directory test db included) would be seeded from a store that is not its own. The
    `legacy_import_done` marker makes it a no-op on every later boot, and INSERT OR IGNORE keeps a
    re-run from duplicating rows. The copy reads the tasks file read-only and drops its `task_id`
    column; the vestigial reminders table is then dropped from the tasks store once the import
    completes.
    """
    if get_meta(conn, _LEGACY_IMPORT_KEY) is not None:
        return
    legacy_db = Path.home() / ".tasks" / "tasks.db"
    if data_dir == default_data_dir() and legacy_db.exists():
        try:
            with closing(sqlite3.connect(f"file:{legacy_db}?mode=ro", uri=True)) as old_conn:
                old_conn.row_factory = sqlite3.Row
                if _has_reminders_table(old_conn):
                    _copy_legacy_rows(old_conn, conn)
        except sqlite3.Error as e:
            # The marker stays unset, so the next init retries instead of losing the box's reminders.
            logger.warning("Failed to import legacy reminders: %s", e)
            return
        # The copy is complete and the tasks daemon no longer reads its reminders table after the
        # skill split, so drop it instead of leaving a dead table in the tasks store forever. A
        # read-write connection, separate from the read-only copy above; a failure is non-fatal
        # because the reminders now live in this store.
        _drop_legacy_reminders_table(legacy_db)
    set_meta(conn, _LEGACY_IMPORT_KEY, datetime.now(UTC).isoformat())


def _drop_legacy_reminders_table(legacy_db: Path):
    """Drop the vestigial `reminders` table from the legacy tasks store after a completed import.

    The tasks daemon no longer reads it after the skill split, so leaving it would keep a dead table
    in the tasks store forever. Read-write, deliberately separate from the read-only copy; a failure
    is non-fatal because the reminders already live in the reminders store."""
    try:
        with closing(sqlite3.connect(legacy_db)) as old_rw:
            old_rw.execute("DROP TABLE IF EXISTS reminders")
            old_rw.commit()
    except sqlite3.Error as e:
        logger.warning("Imported legacy reminders but could not drop the source table: %s", e)


def _copy_legacy_rows(old_conn: sqlite3.Connection, conn: sqlite3.Connection):
    """Copy the hand-written reminders out of a legacy tasks store.

    The tasks store materialized each dated task's pre-due checkpoints as `auto_generated = 1`
    rows; the tasks daemon computes those itself, so only `auto_generated = 0` rows are copied.
    A tasks store already past its own v8 step has neither the column nor such rows."""
    legacy_columns = {row["name"] for row in old_conn.execute("PRAGMA table_info(reminders)")}
    where = " WHERE auto_generated = 0" if "auto_generated" in legacy_columns else ""
    columns = ", ".join(_LEGACY_COLUMNS)
    placeholders = ", ".join("?" for _ in _LEGACY_COLUMNS)
    rows = [tuple(row) for row in old_conn.execute(f"SELECT {columns} FROM reminders{where}")]
    cursor = conn.executemany(f"INSERT OR IGNORE INTO reminders ({columns}) VALUES ({placeholders})", rows)
    logger.info("Imported %s of %s reminders from the legacy tasks store", cursor.rowcount, len(rows))


def init_db(data_dir: Path):
    with closing(get_db(data_dir)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                schedule_type TEXT,
                scheduled_time TEXT,
                completed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                trigger_data TEXT,
                deleted_at TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_completed ON reminders(completed)")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")

        if get_meta(conn, _SCHEMA_VERSION_KEY) is None:
            set_meta(conn, _SCHEMA_VERSION_KEY, str(SCHEMA_VERSION))

        _import_legacy_reminders(conn, data_dir)
        conn.commit()
