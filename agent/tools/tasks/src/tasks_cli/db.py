import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TypedDict


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
    notified_thresholds: str | None


def get_db(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / "tasks.db")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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


def init_db(data_dir: Path):
    with closing(get_db(data_dir)) as conn:
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

        conn.commit()
