import json
import logging
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class Task(TypedDict, total=False):
    id: str
    title: str
    status: str
    priority: int
    due_date: str | None
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
    auto_generated: int


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


def _migrate_v1_to_v2(data_dir: Path, conn: sqlite3.Connection):
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

    # Import reminders from old reminder CLI db if it exists
    old_reminder_db = Path.home() / ".reminder" / "reminders.db"
    if old_reminder_db.exists():
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
                    logger.warning(f"Skipped importing reminder {row['id']}: {e}")
            old_conn.close()
            logger.info(f"Imported {imported} reminders from old reminder CLI")
        except Exception as e:
            logger.warning(f"Failed to import old reminders: {e}")

    # Create auto-generated reminders for all pending tasks with due dates
    _create_auto_reminders_for_existing(conn)

    logger.info("Migrated schema v1 -> v2")


_AUTO_WINDOWS = [
    ("1 week", timedelta(weeks=1)),
    ("1 day", timedelta(days=1)),
    ("1 hour", timedelta(hours=1)),
    ("15 minutes", timedelta(minutes=15)),
]


def _create_auto_reminders_for_existing(conn: sqlite3.Connection):
    """Create auto-generated reminders for all pending tasks with due dates."""
    now = datetime.now(UTC)
    tasks = conn.execute("SELECT id, title, due_date, priority FROM tasks WHERE due_date IS NOT NULL AND status='pending'").fetchall()
    created = 0
    for task in tasks:
        due_str = task["due_date"]
        parsed = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
        if not parsed.tzinfo:
            parsed = parsed.replace(tzinfo=UTC)
        for label, delta in _AUTO_WINDOWS:
            fire_time = parsed - delta
            if fire_time <= now:
                continue
            rid = str(uuid.uuid4())[:8]
            trigger_data = {"type": "date", "run_date": fire_time.isoformat()}
            conn.execute(
                """INSERT INTO reminders (id, task_id, message, schedule_type, scheduled_time, completed, trigger_data, auto_generated)
                   VALUES (?, ?, ?, ?, ?, 0, ?, 1)""",
                (
                    rid,
                    task["id"],
                    f"Task due in {label}: {task['title']}",
                    f"auto: {label} before due",
                    fire_time.isoformat(),
                    json.dumps(trigger_data),
                ),
            )
            created += 1
    if created:
        logger.info(f"Created {created} auto-generated reminders for {len(tasks)} tasks")


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
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'done')),
                priority INTEGER DEFAULT 2 CHECK(priority IN (1, 2, 3)),
                due_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                notified_thresholds TEXT
            )
        """)

        if version < 1:
            _migrate_metadata_to_files(data_dir, conn)
            conn.execute("UPDATE schema_version SET version = 1")
            version = 1

        if version < 2:
            _migrate_v1_to_v2(data_dir, conn)
            conn.execute("UPDATE schema_version SET version = 2")

        conn.commit()

        # Re-enable FK
        conn.execute("PRAGMA foreign_keys = ON")
