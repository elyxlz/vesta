import sqlite3
from contextlib import closing
from pathlib import Path


def get_db(data_dir: Path):
    conn = sqlite3.connect(data_dir / "reminders.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(data_dir: Path):
    import logging
    logger = logging.getLogger(__name__)

    with closing(get_db(data_dir)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                schedule_type TEXT,
                scheduled_time TEXT,
                completed INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                trigger_data TEXT
            )
        """)
        conn.commit()

        # Migrations
        cursor = conn.execute("PRAGMA table_info(reminders)")
        columns = {row[1] for row in cursor.fetchall()}

        if "trigger_data" not in columns:
            conn.execute("ALTER TABLE reminders ADD COLUMN trigger_data TEXT")
            conn.commit()

        if "fired" in columns and "completed" not in columns:
            conn.execute("ALTER TABLE reminders RENAME COLUMN fired TO completed")
            conn.commit()
            logger.info("Migrated 'fired' column to 'completed'")

        conn.execute("DROP TABLE IF EXISTS apscheduler_jobs")
