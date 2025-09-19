#!/usr/bin/env python3
"""One-time migration script to move JSON metadata to SQLite"""

import json
import sqlite3
from pathlib import Path

DATA_DIR = Path("/home/elyx/Repos/vesta2/data/scheduler")
DB_PATH = DATA_DIR / "reminders.db"
JSON_PATH = DATA_DIR / "reminders_metadata.json"

# Connect to database
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Create tables
cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id TEXT PRIMARY KEY,
        message TEXT NOT NULL,
        schedule_type TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS todos (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        priority INTEGER DEFAULT 2,
        due_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT
    )
""")

# Migrate JSON data if it exists
if JSON_PATH.exists():
    print(f"Migrating {JSON_PATH} to SQLite...")
    metadata = json.loads(JSON_PATH.read_text())

    for reminder_id, data in metadata.items():
        cursor.execute(
            """
            INSERT OR IGNORE INTO reminders (id, message, schedule_type)
            VALUES (?, ?, ?)
        """,
            (reminder_id, data["message"], data["schedule_type"]),
        )
        print(f"  Migrated reminder {reminder_id}: {data['message'][:50]}...")

    conn.commit()
    print(f"Migration complete! {len(metadata)} reminders migrated.")

    # Rename JSON file instead of deleting (safety)
    JSON_PATH.rename(JSON_PATH.with_suffix(".json.migrated"))
    print(f"Renamed {JSON_PATH} to {JSON_PATH}.migrated")
else:
    print("No JSON metadata file found, tables created.")

conn.close()
print("Database ready at", DB_PATH)
