"""The chat skill's own durability: every room's messages, the conversation the app shows and the
rooms the agent replicates from the node. A private sqlite db (~/.chat/chat.db) the daemon owns, and
the one source of chat history + search. Ids are skill-assigned (AUTOINCREMENT) and passed through to
the live echo verbatim, so a client cursor stays coherent across the live edge and paged history. A
message the node also holds carries that node id, which is what makes replication idempotent."""

import json
import pathlib as pl
import sqlite3
import threading
import typing as tp

from .attachments import AttachmentMeta

PAGE_SIZE = 50

# The conversation the app renders: the user's messages and the agent's replies. Tool events are not
# shown in chat at all (they ride the wire for Debug only), so this store is pure conversation.
_CONVERSATION_TYPES: tuple[str, ...] = ("user", "chat")

# Relevance decays toward recent so `--search` favors newer matches, mirroring events.py.
_RECENCY_DECAY_RATE = 0.01

# Room and node id are indexed columns, so they never live in the JSON blob as well.
_COLUMN_FIELDS = ("room", "node_id")


class StoredEvent(tp.TypedDict, total=False):
    id: int
    ts: str
    type: str
    text: str
    room: str
    node_id: int | None
    sender: str | None
    input_method: str
    intent_id: str
    attachments: list[AttachmentMeta]


class RoomRecord(tp.TypedDict):
    """One room as the node describes it: its id, the name a group carries, and every agent in it."""

    id: str
    name: str | None
    agents: list[str]


def store_path(data_dir: pl.Path) -> pl.Path:
    """The store's db path under a data dir. The store owns its own filename."""
    return data_dir / "chat.db"


def direct_room_id(agent_name: str) -> str:
    """The room holding the conversation between the user and this agent."""
    return f"dm:{agent_name}"


# FTS5 external-content index over the conversation text, kept in sync by insert/delete triggers, so a
# re-import (INSERT OR IGNORE, no real insert) never double-indexes. Same shape as core's events_fts.
_SCHEMA_V1 = """
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

# Rooms: every message names the room it belongs to, and one carrying a node id is a message the node
# also holds. The unique index is what makes replication idempotent (sqlite allows many NULLs in it, so
# a message the node has never seen stays writable).
_V2_COLUMNS = (
    ("room", "ALTER TABLE events ADD COLUMN room TEXT NOT NULL DEFAULT ''"),
    ("node_id", "ALTER TABLE events ADD COLUMN node_id INTEGER"),
)

_V2_STATEMENTS = (
    "CREATE UNIQUE INDEX IF NOT EXISTS events_node_id ON events(node_id)",
    "CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, name TEXT, agents TEXT NOT NULL)",
)


def _migrate_v1(conn: sqlite3.Connection, _agent_name: str) -> None:
    """The baseline, every statement `IF NOT EXISTS`, so re-running it changes nothing."""
    conn.executescript(_SCHEMA_V1)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()


def _migrate_v2(conn: sqlite3.Connection, agent_name: str) -> None:
    """Rooms and node ids. Every row already stored is the conversation between the user and this
    agent, so the whole history is filed under the direct room and paging, search and replication read
    one coherent conversation.

    The whole step is one transaction, and `ADD COLUMN` runs only for a column the table does not
    list, so an open that dies mid-step and a second process opening the same db both converge here
    rather than on `duplicate column name`."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        if conn.execute("PRAGMA user_version").fetchone()[0] >= 2:
            conn.rollback()
            return
        stored = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
        for column, statement in _V2_COLUMNS:
            if column not in stored:
                conn.execute(statement)
        for statement in _V2_STATEMENTS:
            conn.execute(statement)
        conn.execute("UPDATE events SET room = ?", (direct_room_id(agent_name),))
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


# `PRAGMA user_version` is the on-disk version; a step's position in this list is the version it
# stamps, and each step stamps and commits its own version, so it owns how it stays safe to re-run.
# Version 1 is the baseline (all `CREATE ... IF NOT EXISTS`), so a fresh db and a db written before
# versioning both converge on it with no data loss. Add a schema change as a version 3 step; never
# edit a released step, since existing dbs have already run it.
_MIGRATIONS: tuple[tp.Callable[[sqlite3.Connection, str], None], ...] = (_migrate_v1, _migrate_v2)


def _migrate(conn: sqlite3.Connection, agent_name: str) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for index, step in enumerate(_MIGRATIONS):
        if current < index + 1:
            step(conn, agent_name)


def _open(db_path: pl.Path, agent_name: str) -> sqlite3.Connection:
    """The writer connection. It is opened for any thread because the daemon writes from the loop and
    from the replica's worker threads; `Store` serializes every use of it behind its own lock."""
    conn = sqlite3.connect(str(db_path), timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    _migrate(conn, agent_name)
    return conn


_ROW_COLUMNS = "id, ts, data, room, node_id"


def _rows_to_events(rows: list[tuple[int, str, str, str, int | None]]) -> list[StoredEvent]:
    events: list[StoredEvent] = []
    for row in rows:
        event: StoredEvent = json.loads(row[2])
        event["id"] = row[0]
        # Legacy imports stored the timestamp in the indexed SQLite column but not inside the JSON
        # payload. Hydrate it on every read so clients can bucket those messages by their real date.
        event.setdefault("ts", row[1])
        event["room"] = row[3]
        if row[4] is not None:
            event["node_id"] = row[4]
        events.append(event)
    return events


def _row_to_room(row: tuple[str, str | None, str]) -> RoomRecord:
    return {"id": row[0], "name": row[1], "agents": json.loads(row[2])}


class Store:
    """Single-writer store owned by the serve process; readers (the CLI, the paged read) open their own
    short-lived WAL connections. `append` stamps the next AUTOINCREMENT id and files the message under a
    room (the direct room when the caller names none); `page` reads oldest-to-newest with an id cursor;
    `search` runs FTS5 relevance ranking decayed toward recent. Every write holds the store's lock, so
    the daemon's own send path and the replica's worker threads share one connection safely."""

    def __init__(self, db_path: pl.Path, agent_name: str) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.direct_room = direct_room_id(agent_name)
        self._lock = threading.RLock()
        self._conn = _open(db_path, agent_name)
        self._db_path = db_path

    def _read(self) -> sqlite3.Connection:
        """A short-lived read connection, so a scan never interleaves with the writer's transaction."""
        return sqlite3.connect(str(self._db_path), timeout=30)

    def append(self, event: StoredEvent) -> int:
        room = event["room"] if "room" in event else self.direct_room
        node_id = event["node_id"] if "node_id" in event else None
        blob = {key: value for key, value in event.items() if key not in _COLUMN_FIELDS}
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO events (ts, data, room, node_id) VALUES (?, ?, ?, ?)",
                (event["ts"], json.dumps(blob), room, node_id),
            )
            self._conn.commit()
            rowid = cursor.lastrowid
        if rowid is None:
            raise sqlite3.Error("insert returned no rowid")
        event["id"] = rowid
        event["room"] = room
        return rowid

    def mark_node_id(self, local_id: int, node_id: int) -> None:
        """Record that the node also holds this row, so replicating it back is a no-op."""
        with self._lock:
            self._conn.execute("UPDATE events SET node_id = ? WHERE id = ?", (node_id, local_id))
            self._conn.commit()

    def has_node_id(self, node_id: int) -> bool:
        conn = self._read()
        try:
            return conn.execute("SELECT 1 FROM events WHERE node_id = ? LIMIT 1", (node_id,)).fetchone() is not None
        finally:
            conn.close()

    def max_node_id(self, room: str) -> int:
        """The newest node id stored for a room, 0 when the room holds none. The pull asks the node for
        everything after it, so a replica that fell behind resumes where it stopped."""
        conn = self._read()
        try:
            highest = conn.execute("SELECT MAX(node_id) FROM events WHERE room = ?", (room,)).fetchone()[0]
        finally:
            conn.close()
        return 0 if highest is None else int(highest)

    def local_id_for_origin(self, room: str, origin_id: int) -> int | None:
        """The local row an imported message came from: the node echoes back the id the import carried,
        which is this store's own row id, so the row it names is stamped instead of duplicated."""
        conn = self._read()
        try:
            row = conn.execute("SELECT id FROM events WHERE id = ? AND room = ?", (origin_id, room)).fetchone()
        finally:
            conn.close()
        return None if row is None else int(row[0])

    def page(self, limit: int = PAGE_SIZE, before_cursor: int | None = None, room: str | None = None) -> tuple[list[StoredEvent], int | None]:
        """The last `limit` conversation events before `before_cursor` (exclusive), oldest-to-newest,
        with the next-older cursor (None when no older page). A room reads that room alone; no room
        reads every one."""
        if limit <= 0:
            return [], None
        clauses = ""
        params: list[str | int] = []
        if room is not None:
            clauses += "AND room = ? "
            params.append(room)
        if before_cursor is not None:
            clauses += "AND id < ? "
            params.append(before_cursor)
        placeholders = ",".join("?" for _ in _CONVERSATION_TYPES)
        conn = self._read()
        try:
            rows = conn.execute(
                f"SELECT {_ROW_COLUMNS} FROM events WHERE json_extract(data, '$.type') IN ({placeholders}) {clauses}ORDER BY id DESC LIMIT ?",
                (*_CONVERSATION_TYPES, *params, limit + 1),
            ).fetchall()
        finally:
            conn.close()
        if not rows:
            return [], None
        has_older = len(rows) > limit
        rows = rows[:limit]
        return _rows_to_events(list(reversed(rows))), rows[-1][0] if has_older else None

    def search(self, query: str, *, limit: int = 20, room: str | None = None) -> list[StoredEvent]:
        """Full-text search over the conversation, ranked by FTS relevance decayed toward recent (mirrors
        events.db), across every room or one named room. A malformed MATCH raises
        sqlite3.OperationalError, which the caller maps to a client error."""
        room_clause = "AND e.room = ? " if room is not None else ""
        room_params: tuple[str, ...] = (room,) if room is not None else ()
        conn = self._read()
        try:
            rows = conn.execute(
                f"""
                SELECT e.id, e.ts, e.data, e.room, e.node_id,
                       f.rank / (1.0 + ? * max(julianday('now') - julianday(e.ts), 0)) AS score
                FROM events_fts f
                JOIN events e ON e.id = f.rowid
                WHERE events_fts MATCH ? {room_clause}
                ORDER BY score ASC
                LIMIT ?
                """,
                (_RECENCY_DECAY_RATE, query, *room_params, limit),
            ).fetchall()
        finally:
            conn.close()
        return _rows_to_events([(row[0], row[1], row[2], row[3], row[4]) for row in rows])

    def unsynced_direct_rows(self) -> list[StoredEvent]:
        """Every conversation row of the direct room the node does not hold yet, oldest first: what
        `chat import-to-node` hands the node so the shared history starts complete."""
        placeholders = ",".join("?" for _ in _CONVERSATION_TYPES)
        conn = self._read()
        try:
            rows = conn.execute(
                f"SELECT {_ROW_COLUMNS} FROM events "
                f"WHERE room = ? AND node_id IS NULL AND json_extract(data, '$.type') IN ({placeholders}) ORDER BY id ASC",
                (self.direct_room, *_CONVERSATION_TYPES),
            ).fetchall()
        finally:
            conn.close()
        return _rows_to_events(rows)

    def upsert_room(self, room: RoomRecord) -> None:
        """Store a room as the node describes it now, name and membership included."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO rooms (id, name, agents) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name = excluded.name, agents = excluded.agents",
                (room["id"], room["name"], json.dumps(room["agents"])),
            )
            self._conn.commit()

    def rooms(self) -> list[RoomRecord]:
        conn = self._read()
        try:
            rows = conn.execute("SELECT id, name, agents FROM rooms ORDER BY id ASC").fetchall()
        finally:
            conn.close()
        return [_row_to_room(row) for row in rows]

    def room(self, room_id: str) -> RoomRecord | None:
        conn = self._read()
        try:
            row = conn.execute("SELECT id, name, agents FROM rooms WHERE id = ?", (room_id,)).fetchone()
        finally:
            conn.close()
        return None if row is None else _row_to_room(row)

    def delete_room(self, room_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
            self._conn.commit()

    def attachment_references(self) -> dict[str, tuple[str, str]]:
        """Every attachment id any event references, mapped to that event's (ts, type). One structured
        scan of the `$.attachments` arrays (never a substring probe, so chat text quoting an id can not
        pin a blob), first event wins. Backs both the GC sweep and `attachments list`."""
        conn = self._read()
        try:
            rows = conn.execute(
                """
                SELECT json_extract(entry.value, '$.id'), events.ts, json_extract(events.data, '$.type')
                FROM events, json_each(events.data, '$.attachments') AS entry
                ORDER BY events.id ASC
                """
            ).fetchall()
        finally:
            conn.close()
        references: dict[str, tuple[str, str]] = {}
        for attachment_id, ts, event_type in rows:
            if isinstance(attachment_id, str) and attachment_id not in references:
                references[attachment_id] = (ts, event_type)
        return references

    def import_rows(self, rows: list[tuple[int, str, str]]) -> tuple[int, int]:
        """Copy (id, ts, data) triples from events.db preserving ids, idempotently (INSERT OR IGNORE).
        They are the conversation between the user and this agent, so they land in the direct room. The
        AFTER INSERT trigger indexes each real insert into FTS, so imported history is searchable.
        Returns (count_written, max_id_seen) so the caller can bump the sequence above it (see D3)."""
        count = 0
        max_id = 0
        with self._lock:
            for row_id, ts, data in rows:
                cursor = self._conn.execute(
                    "INSERT OR IGNORE INTO events (id, ts, data, room) VALUES (?, ?, ?, ?)", (row_id, ts, data, self.direct_room)
                )
                count += cursor.rowcount
                max_id = max(max_id, row_id)
            self._conn.commit()
        return count, max_id

    def bump_sequence_above(self, max_id: int) -> None:
        """Keep AUTOINCREMENT strictly above an imported id set (D3): a freshly imported store must
        never re-mint an id a client already cached as a cursor."""
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO sqlite_sequence(name, seq) VALUES ('events', 0)")
            self._conn.execute("UPDATE sqlite_sequence SET seq = MAX(seq, ?) WHERE name = 'events'", (max_id,))
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
