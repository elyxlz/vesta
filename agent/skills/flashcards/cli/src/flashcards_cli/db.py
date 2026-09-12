"""The sqlite store: schema, connection, meta keys, and the one datetime format every row uses."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DB_NAME = "flashcards.db"

# Every stored instant is UTC at second precision in this exact shape, so ISO strings compare
# lexicographically in SQL.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    deleted_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS decks_live_name ON decks (name) WHERE deleted_at IS NULL;
CREATE TABLE IF NOT EXISTS cards (
    id INTEGER PRIMARY KEY,
    deck_id INTEGER NOT NULL REFERENCES decks (id),
    front TEXT NOT NULL,
    back TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    fsrs TEXT NOT NULL,
    state INTEGER NOT NULL,
    due TEXT NOT NULL,
    last_review TEXT,
    created_at TEXT NOT NULL,
    suspended_at TEXT,
    deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS cards_due ON cards (due) WHERE deleted_at IS NULL AND suspended_at IS NULL;
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    card_id INTEGER NOT NULL REFERENCES cards (id),
    rating INTEGER NOT NULL,
    reviewed_at TEXT NOT NULL,
    duration_secs INTEGER,
    log TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_card ON reviews (card_id, reviewed_at);
"""


def get_db(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = get_db(data_dir)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(instant: datetime) -> str:
    return instant.astimezone(UTC).replace(microsecond=0).isoformat()


def parse_datetime(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    conn.commit()
