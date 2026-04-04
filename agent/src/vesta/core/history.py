"""Conversation history persistence with SQLite + FTS5 full-text search."""

import dataclasses
import datetime as dt
import pathlib as pl
import sqlite3


_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    session_id TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content,
    content='messages',
    content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, content) VALUES ('delete', old.id, old.content);
    INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
END;
"""


@dataclasses.dataclass
class HistoryDB:
    conn: sqlite3.Connection


def open_history(db_path: pl.Path) -> HistoryDB:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(_SCHEMA)
    return HistoryDB(conn=conn)


def history_save(db: HistoryDB, role: str, content: str, *, session_id: str | None = None, timestamp: dt.datetime | None = None) -> None:
    ts = (timestamp or dt.datetime.now()).isoformat()
    db.conn.execute(
        "INSERT INTO messages (timestamp, role, content, session_id) VALUES (?, ?, ?, ?)",
        (ts, role, content, session_id),
    )
    db.conn.commit()


_RECENCY_DECAY_RATE = 0.01


def history_search(db: HistoryDB, query: str, *, limit: int = 20) -> list[dict[str, str]]:
    rows = db.conn.execute(
        """
        SELECT m.timestamp, m.role, m.content
        FROM messages_fts f
        JOIN messages m ON m.id = f.rowid
        WHERE messages_fts MATCH ?
        ORDER BY f.rank / (1.0 + ? * max(julianday('now') - julianday(m.timestamp), 0)) ASC
        LIMIT ?
        """,
        (query, _RECENCY_DECAY_RATE, limit),
    ).fetchall()
    return [{"timestamp": r[0], "role": r[1], "content": r[2]} for r in rows]


def history_get_range(
    db: HistoryDB, *, since: dt.datetime | None = None, until: dt.datetime | None = None, limit: int = 100
) -> list[dict[str, str]]:
    conditions = []
    params: list[str | int] = []
    if since:
        conditions.append("timestamp >= ?")
        params.append(since.isoformat())
    if until:
        conditions.append("timestamp <= ?")
        params.append(until.isoformat())
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = db.conn.execute(
        f"SELECT timestamp, role, content FROM messages {where} ORDER BY id DESC LIMIT ?",
        params,
    ).fetchall()
    return [{"timestamp": r[0], "role": r[1], "content": r[2]} for r in reversed(rows)]


def format_results(results: list[dict[str, str]], *, max_chars: int = 50000) -> str:
    if not results:
        return "No results found."
    lines = []
    total = 0
    for r in results:
        content = r["content"]
        if len(content) > 2000:
            content = content[:2000] + "..."
        line = f"[{r['timestamp']}] {r['role']}: {content}"
        if total + len(line) > max_chars:
            lines.append(f"... ({len(results) - len(lines)} more results truncated)")
            break
        lines.append(line)
        total += len(line)
    return "\n\n".join(lines)
