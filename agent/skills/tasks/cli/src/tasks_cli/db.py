import json
import logging
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

from .config import default_data_dir

logger = logging.getLogger(__name__)

# Head schema version. Bump this in the same commit as a new _migrate_vN_to_vN+1, and assert against
# it in tests rather than hard-coding an integer, so adding a migration cannot break unrelated tests.
SCHEMA_VERSION = 8


class Task(TypedDict, total=False):
    id: str
    subject: str
    status: str
    priority: int
    due_date: str | None
    backburner: int
    metadata_path: str | None
    metadata_content: str | None
    created_at: str
    completed_at: str | None


class Reminder(TypedDict, total=False):
    id: str
    task_id: str | None
    message: str
    schedule_type: str | None
    scheduled_time: str | None
    completed: int
    created_at: str
    trigger_data: str | None


def get_db(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / "tasks.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_metadata_to_files(data_dir: Path, conn: sqlite3.Connection):
    """Migrate metadata from database TEXT column to individual files."""
    metadata_dir = data_dir / "metadata"
    metadata_dir.mkdir(exist_ok=True)

    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor]
    if "metadata" not in columns:
        return

    cursor = conn.execute("SELECT id, metadata FROM tasks WHERE metadata IS NOT NULL")
    for row in cursor:
        task_id, metadata = row
        if metadata:
            (metadata_dir / f"{task_id}.md").write_text(metadata)

    conn.execute("""
        CREATE TABLE tasks_new (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
            priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
            due_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            notified_thresholds TEXT
        )
    """)
    conn.execute("""
        INSERT INTO tasks_new (id, title, status, priority, due_date, created_at, completed_at, notified_thresholds)
        SELECT id, title, status, priority, due_date, created_at, completed_at, notified_thresholds FROM tasks
    """)
    conn.execute("DROP TABLE tasks")
    conn.execute("ALTER TABLE tasks_new RENAME TO tasks")


def _migrate_v1_to_v2(conn: sqlite3.Connection, data_dir: Path):
    """v1 -> v2: Create reminders table, drop notified_thresholds, import old reminders."""

    # Create reminders table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            message TEXT NOT NULL,
            schedule_type TEXT,
            scheduled_time TEXT,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            trigger_data TEXT,
            auto_generated INTEGER DEFAULT 0,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_completed ON reminders(completed)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_task_id ON reminders(task_id)")

    # Drop notified_thresholds column (SQLite: recreate table)
    cursor = conn.execute("PRAGMA table_info(tasks)")
    columns = [row[1] for row in cursor]
    if "notified_thresholds" in columns:
        conn.execute("""
            CREATE TABLE tasks_v2 (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
        """)
        conn.execute("""
            INSERT INTO tasks_v2 (id, title, status, priority, due_date, created_at, completed_at)
            SELECT id, title, status, priority, due_date, created_at, completed_at FROM tasks
        """)
        conn.execute("DROP TABLE tasks")
        conn.execute("ALTER TABLE tasks_v2 RENAME TO tasks")

    # LEGACY(remove-when: no fleet agent's tasks.db remains below schema v2): one-time import from the
    # old reminder CLI db, and ONLY into the real store. The legacy path is absolute and home-relative
    # while the database being built is whatever the caller passed, so without this guard every new
    # database (a temp-directory test db included) gets seeded from a store that isn't its own.
    old_reminder_db = Path.home() / ".reminder" / "reminders.db"
    if data_dir == default_data_dir() and old_reminder_db.exists():
        try:
            old_conn = sqlite3.connect(old_reminder_db)
            old_conn.row_factory = sqlite3.Row
            old_cursor = old_conn.execute("SELECT * FROM reminders")
            imported = 0
            for row in old_cursor:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO reminders
                           (id, task_id, message, schedule_type, scheduled_time, completed, created_at, trigger_data, auto_generated)
                           VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 0)""",
                        (
                            row["id"],
                            row["message"],
                            row["schedule_type"],
                            row["scheduled_time"],
                            row["completed"],
                            row["created_at"],
                            row["trigger_data"],
                        ),
                    )
                    imported += 1
                except (KeyError, sqlite3.Error) as e:
                    logger.warning("Skipped importing reminder %s: %s", row["id"], e)
            old_conn.close()
            logger.info("Imported %s reminders from old reminder CLI", imported)
        except Exception as e:
            logger.warning("Failed to import old reminders: %s", e)

    # Create auto-generated reminders for all pending tasks with due dates
    _create_auto_reminders_for_existing(conn)

    logger.info("Migrated schema v1 -> v2")


def _migrate_v2_to_v3(conn: sqlite3.Connection):
    """v2 -> v3: rewrite legacy cron reminders from UTC-baked fields to the {expr, tz} form.

    Old recurring reminders stored a fixed UTC hour/minute (plus optional day/month/day_of_week)
    with no timezone, so they silently drifted by an hour across every DST transition. Rewrite each
    to an equivalent cron expression tagged tz='UTC', which preserves their exact current firing
    instants; reminders created after this upgrade carry the user's real IANA timezone and stay put
    across DST. Idempotent: rows already in {expr, tz} form are skipped."""
    rows = conn.execute("SELECT id, trigger_data FROM reminders WHERE trigger_data IS NOT NULL").fetchall()
    migrated = 0
    for row in rows:
        data = json.loads(row["trigger_data"])
        if "type" not in data or data["type"] != "cron" or "expr" in data:
            continue
        minute = data["minute"] if "minute" in data else "*"
        hour = data["hour"] if "hour" in data else "*"
        day = data["day"] if "day" in data else "*"
        month = data["month"] if "month" in data else "*"
        dow = data["day_of_week"] if "day_of_week" in data else "*"
        new_data = {"type": "cron", "expr": f"{minute} {hour} {day} {month} {dow}", "tz": "UTC"}
        conn.execute("UPDATE reminders SET trigger_data = ? WHERE id = ?", (json.dumps(new_data), row["id"]))
        migrated += 1
    if migrated:
        logger.info("Migrated %s legacy cron reminders to tz-aware form", migrated)
    logger.info("Migrated schema v2 -> v3")


# --- Materialized auto-reminder ladder, frozen for the released v1->v2 and v3->v4 migration
# steps above and below, which built these rows for dbs that predate them. Live checkpoints are
# computed in commands.py (checkpoint_times / fire_due_checkpoints); nothing else calls this block.
AUTO_REMINDER_TAIL = [
    ("1 week", timedelta(weeks=1)),
    ("1 day", timedelta(days=1)),
    ("1 hour", timedelta(hours=1)),
    ("15 minutes", timedelta(minutes=15)),
]

CHECKPOINT_FLOOR = timedelta(weeks=2)

DUE_NOW_MESSAGE = (
    'Task "{title}" ({task_id}) is due now. Decide immediately: do it and run `tasks done {task_id}`, '
    "or postpone it (`tasks postpone {task_id} --in-days N`), or tell the user you are dropping it and run "
    "`tasks delete {task_id}`. Never leave a task sitting overdue."
)

LEAD_TIME_MESSAGE = "Task due in {label}: {title}"

# `schedule_type` labels for the two auto-reminder shapes. A rung's lead time is recoverable from
# its label, which is what lets a retitle regenerate the body without rebuilding the ladder.
AT_DUE_SCHEDULE = "auto: at due"
_LEAD_SCHEDULE_PREFIX = "auto: "
_LEAD_SCHEDULE_SUFFIX = " before due"


def lead_time_schedule(label: str) -> str:
    return f"{_LEAD_SCHEDULE_PREFIX}{label}{_LEAD_SCHEDULE_SUFFIX}"


def parse_datetime(s: str) -> datetime:
    parsed = datetime.fromisoformat(s)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _humanize_delta(delta: timedelta) -> str:
    days = round(delta.total_seconds() / 86400)
    if days >= 60:
        return f"about {round(days / 30)} months"
    return f"about {round(days / 7)} weeks"


def auto_reminder_deltas(lead: timedelta) -> list[tuple[str, timedelta]]:
    """Lead-time offsets for a task's auto reminders: checkpoints that halve the remaining lead
    while they stay more than two weeks out, then the fixed 1w/1d/1h/15m tail."""
    checkpoints = []
    half = lead / 2
    while half > CHECKPOINT_FLOOR:
        checkpoints.append((_humanize_delta(half), half))
        half = half / 2
    return checkpoints + AUTO_REMINDER_TAIL


def _insert_auto_reminder(conn: sqlite3.Connection, task_id: str, message: str, schedule_type: str, fire_time: datetime):
    trigger_data = {"type": "date", "run_date": fire_time.isoformat()}
    conn.execute(
        """INSERT INTO reminders (id, task_id, message, schedule_type, scheduled_time, completed, trigger_data, auto_generated)
           VALUES (?, ?, ?, ?, ?, 0, ?, 1)""",
        (str(uuid.uuid4())[:8], task_id, message, schedule_type, fire_time.isoformat(), json.dumps(trigger_data)),
    )


def create_auto_reminders(conn: sqlite3.Connection, task_id: str, title: str, due_date_str: str):
    now = datetime.now(UTC)
    due_dt = parse_datetime(due_date_str)
    # A rung the user rewrote is owned (auto_generated = 0) and survives the delete before a rebuild,
    # so skip any instant already occupied rather than firing a second reminder alongside it.
    taken = {row["scheduled_time"] for row in conn.execute("SELECT scheduled_time FROM reminders WHERE task_id = ?", (task_id,))}

    for label, delta in auto_reminder_deltas(due_dt - now):
        fire_time = due_dt - delta
        if fire_time <= now or fire_time.isoformat() in taken:
            continue
        _insert_auto_reminder(conn, task_id, LEAD_TIME_MESSAGE.format(label=label, title=title), lead_time_schedule(label), fire_time)

    if due_dt > now and due_dt.isoformat() not in taken:
        _insert_auto_reminder(conn, task_id, DUE_NOW_MESSAGE.format(title=title, task_id=task_id), AT_DUE_SCHEDULE, due_dt)


def delete_task_reminders(conn: sqlite3.Connection, task_id: str):
    conn.execute("DELETE FROM reminders WHERE task_id = ?", (task_id,))


def _create_auto_reminders_for_existing(conn: sqlite3.Connection):
    """Create auto-generated reminders for all pending tasks with due dates."""
    tasks = conn.execute("SELECT id, title, due_date FROM tasks WHERE due_date IS NOT NULL AND status != 'done'").fetchall()
    created = 0
    for task in tasks:
        create_auto_reminders(conn, task["id"], task["title"], task["due_date"])
        created += 1
    if created:
        logger.info("Created auto-generated reminders for %s tasks", created)


def _migrate_v3_to_v4(conn: sqlite3.Connection):
    """v3 -> v4: add the meta key-value table (digest bookkeeping) and regenerate pending auto
    reminders so existing tasks pick up the at-due decision fire and the spaced checkpoints."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("DELETE FROM reminders WHERE auto_generated = 1 AND completed = 0")
    _create_auto_reminders_for_existing(conn)
    logger.info("Migrated schema v3 -> v4")


def _migrate_v4_to_v5(conn: sqlite3.Connection):
    """v4 -> v5: add the `backburner` flag.

    Set on a task that is deliberately undated, because someone else drives it or it is a genuine
    someday-maybe. It defers the nag, never the task: a parked task stays pending, stays visible in
    `tasks list` marked [parked], and only stops appearing in the stale-task digest.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "backburner" not in cols:
        conn.execute("ALTER TABLE tasks ADD COLUMN backburner INTEGER NOT NULL DEFAULT 0")
    logger.info("Migrated schema v4 -> v5")


def _migrate_v5_to_v6(conn: sqlite3.Connection):
    """v5 -> v6: widen the status CHECK to allow 'in_progress' (the CLI also accepts 'completed' as
    an alias for 'done'). SQLite cannot alter a CHECK in place, so rebuild the table, preserving
    every row and column."""
    conn.execute("""
        CREATE TABLE tasks_v6 (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'done')),
            priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
            due_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            backburner INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        INSERT INTO tasks_v6 (id, title, status, priority, due_date, created_at, completed_at, backburner)
        SELECT id, title, status, priority, due_date, created_at, completed_at, backburner FROM tasks
    """)
    conn.execute("DROP TABLE tasks")
    conn.execute("ALTER TABLE tasks_v6 RENAME TO tasks")
    logger.info("Migrated schema v5 -> v6")


def _migrate_v7_to_v8(conn: sqlite3.Connection):
    """v7 -> v8: due-date checkpoints become computed instead of stored.

    Adds tasks.checkpoint_fired_through (the single piece of checkpoint state), deletes the
    materialized auto-reminder rows, and rebuilds reminders without the auto_generated column.
    A rung the user rewrote carries auto_generated = 0 and survives as the plain reminder it
    became. checkpoint_fired_through starts at now so an in-flight ladder continues from here
    instead of refiring rungs the deleted rows already delivered."""
    conn.execute("ALTER TABLE tasks ADD COLUMN checkpoint_fired_through TEXT")
    conn.execute("UPDATE tasks SET checkpoint_fired_through = strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') WHERE due_date IS NOT NULL")
    conn.execute("DELETE FROM reminders WHERE auto_generated = 1")
    conn.execute("""
        CREATE TABLE reminders_v8 (
            id TEXT PRIMARY KEY,
            task_id TEXT,
            message TEXT NOT NULL,
            schedule_type TEXT,
            scheduled_time TEXT,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            trigger_data TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
        )
    """)
    conn.execute("""
        INSERT INTO reminders_v8 (id, task_id, message, schedule_type, scheduled_time, completed, created_at, trigger_data)
        SELECT id, task_id, message, schedule_type, scheduled_time, completed, created_at, trigger_data FROM reminders
    """)
    conn.execute("DROP TABLE reminders")
    conn.execute("ALTER TABLE reminders_v8 RENAME TO reminders")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_completed ON reminders(completed)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_reminders_task_id ON reminders(task_id)")
    logger.info("Migrated schema v7 -> v8")


def _migrate_v6_to_v7(conn: sqlite3.Connection):
    """v6 -> v7: rename the `title` column to `subject` and the `done` status value to `completed`.
    SQLite cannot alter a column name inside a CHECK in place, so rebuild the table, preserving
    every row."""
    conn.execute("""
        CREATE TABLE tasks_v7 (
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
        INSERT INTO tasks_v7 (id, subject, status, priority, due_date, created_at, completed_at, backburner)
        SELECT id, title, CASE WHEN status = 'done' THEN 'completed' ELSE status END,
               priority, due_date, created_at, completed_at, backburner FROM tasks
    """)
    conn.execute("DROP TABLE tasks")
    conn.execute("ALTER TABLE tasks_v7 RENAME TO tasks")
    logger.info("Migrated schema v6 -> v7")


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def init_db(data_dir: Path):
    with closing(get_db(data_dir)) as conn:
        # Temporarily disable FK for migration (table recreation)
        conn.execute("PRAGMA foreign_keys = OFF")

        conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)")
        cursor = conn.execute("SELECT version FROM schema_version")
        row = cursor.fetchone()
        if not row:
            conn.execute("INSERT INTO schema_version (version) VALUES (0)")
            version = 0
        else:
            version = row[0]

        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'in_progress', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                notified_thresholds TEXT,
                backburner INTEGER NOT NULL DEFAULT 0
            )
        """)

        if version < 1:
            _migrate_metadata_to_files(data_dir, conn)
            conn.execute("UPDATE schema_version SET version = 1")
            version = 1

        if version < 2:
            _migrate_v1_to_v2(conn, data_dir)
            conn.execute("UPDATE schema_version SET version = 2")
            version = 2

        if version < 3:
            _migrate_v2_to_v3(conn)
            conn.execute("UPDATE schema_version SET version = 3")
            version = 3

        if version < 4:
            _migrate_v3_to_v4(conn)
            conn.execute("UPDATE schema_version SET version = 4")
            version = 4

        if version < 5:
            _migrate_v4_to_v5(conn)
            conn.execute("UPDATE schema_version SET version = 5")
            version = 5

        if version < 6:
            _migrate_v5_to_v6(conn)
            conn.execute("UPDATE schema_version SET version = 6")
            version = 6

        if version < 7:
            _migrate_v6_to_v7(conn)
            conn.execute("UPDATE schema_version SET version = 7")
            version = 7

        if version < 8:
            _migrate_v7_to_v8(conn)
            conn.execute("UPDATE schema_version SET version = 8")
            version = 8

        conn.commit()

        # Re-enable FK
        conn.execute("PRAGMA foreign_keys = ON")
