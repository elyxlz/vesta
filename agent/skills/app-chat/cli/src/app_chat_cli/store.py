"""The app-chat skill's own durability: user messages and the agent's replies, the conversation the
app shows. A private sqlite db (~/.app-chat/app-chat.db) the daemon owns, replacing core's events.db
as the source of app-chat history + search. Ids are skill-assigned (AUTOINCREMENT) and passed through
to the live echo verbatim, so a client cursor stays coherent across the live edge and paged history."""

import json
import pathlib as pl
import sqlite3
import typing as tp

PAGE_SIZE = 50

# The conversation the app renders: the user's messages and the agent's replies. Tool events are not
# shown in chat at all (they ride the wire for Debug only), so this store is pure conversation.
_CONVERSATION_TYPES: tuple[str, ...] = ("user", "chat")

# Relevance decays toward recent so `--search` favors newer matches, mirroring events.py.
_RECENCY_DECAY_RATE = 0.01


class StoredEvent(tp.TypedDict, total=False):
    id: int
    ts: str
    type: str
    text: str
    input_method: str
    intent_id: str


def store_path(data_dir: pl.Path) -> pl.Path:
    """The store's db path under a data dir. The store owns its own filename."""
    return data_dir / "app-chat.db"


# FTS5 external-content index over the conversation text, kept in sync by insert/delete triggers, so a
# re-import (INSERT OR IGNORE, no real insert) never double-indexes. Same shape as core's events_fts.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    text_content,
    content='events',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS events_fts_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, text_content)
    SELECT new.id, json_extract(new.data, '$.text')
    WHERE json_extract(new.data, '$.type') IN ('user', 'chat');
END;

CREATE TRIGGER IF NOT EXISTS events_fts_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, text_content)
    SELECT 'delete', old.id, json_extract(old.data, '$.text')
    WHERE json_extract(old.data, '$.type') IN ('user', 'chat');
END;
"""


def _open(db_path: pl.Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def _rows_to_events(rows: list[tuple[int, str]]) -> list[StoredEvent]:
    events: list[StoredEvent] = []
    for row in rows:
        event: StoredEvent = json.loads(row[1])
        event["id"] = row[0]
        events.append(event)
    return events


class Store:
    """Single-writer store owned by the serve process; readers (the CLI, the paged read) open their own
    short-lived WAL connections. `append` stamps the next AUTOINCREMENT id; `page` reads oldest-to-newest
    with an id cursor; `search` runs FTS5 relevance ranking decayed toward recent."""

    def __init__(self, db_path: pl.Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = _open(db_path)
        self._db_path = db_path

    def append(self, event: StoredEvent) -> int:
        cursor = self._conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", (event["ts"], json.dumps(event)))
        self._conn.commit()
        rowid = cursor.lastrowid
        if rowid is None:
            raise sqlite3.Error("insert returned no rowid")
        event["id"] = rowid
        return rowid

    def page(self, limit: int = PAGE_SIZE, before_cursor: int | None = None) -> tuple[list[StoredEvent], int | None]:
        """The last `limit` conversation events before `before_cursor` (exclusive), oldest-to-newest,
        with the next-older cursor (None when no older page). Short-lived read connection so it never
        interleaves with the writer's transaction."""
        if limit <= 0:
            return [], None
        upper = "AND id < ? " if before_cursor is not None else ""
        params: tuple[object, ...] = (before_cursor,) if before_cursor is not None else ()
        placeholders = ",".join("?" for _ in _CONVERSATION_TYPES)
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        try:
            rows = conn.execute(
                f"SELECT id, data FROM events WHERE json_extract(data, '$.type') IN ({placeholders}) {upper}ORDER BY id DESC LIMIT ?",
                (*_CONVERSATION_TYPES, *params, limit + 1),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return [], None
        has_older = len(rows) > limit
        rows = rows[:limit]
        return _rows_to_events(list(reversed(rows))), rows[-1][0] if has_older else None

    def search(self, query: str, *, limit: int = 20) -> list[StoredEvent]:
        """Full-text search over the conversation, ranked by FTS relevance decayed toward recent (mirrors
        events.db). Short-lived read connection so a big scan never blocks the writer. A malformed MATCH
        raises sqlite3.OperationalError, which the caller maps to a client error."""
        conn = sqlite3.connect(str(self._db_path), timeout=30)
        try:
            rows = conn.execute(
                """
                SELECT e.id, e.data,
                       f.rank / (1.0 + ? * max(julianday('now') - julianday(e.ts), 0)) AS score
                FROM events_fts f
                JOIN events e ON e.id = f.rowid
                WHERE events_fts MATCH ?
                ORDER BY score ASC
                LIMIT ?
                """,
                (_RECENCY_DECAY_RATE, query, limit),
            ).fetchall()
        finally:
            conn.close()
        return _rows_to_events([(row[0], row[1]) for row in rows])

    def import_rows(self, rows: list[tuple[int, str, str]]) -> tuple[int, int]:
        """Copy (id, ts, data) triples from events.db preserving ids, idempotently (INSERT OR IGNORE).
        The AFTER INSERT trigger indexes each real insert into FTS, so imported history is searchable.
        Returns (count_written, max_id_seen) so the caller can bump the sequence above it (see D3)."""
        count = 0
        max_id = 0
        for row_id, ts, data in rows:
            cursor = self._conn.execute("INSERT OR IGNORE INTO events (id, ts, data) VALUES (?, ?, ?)", (row_id, ts, data))
            count += cursor.rowcount
            max_id = max(max_id, row_id)
        self._conn.commit()
        return count, max_id

    def bump_sequence_above(self, max_id: int) -> None:
        """Keep AUTOINCREMENT strictly above an imported id set (D3): a freshly imported store must
        never re-mint an id a client already cached as a cursor."""
        self._conn.execute("INSERT OR IGNORE INTO sqlite_sequence(name, seq) VALUES ('events', 0)")
        self._conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'events'", (max_id,))
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
