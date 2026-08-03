import json
import pathlib
import sqlite3
import typing as tp

import pytest

# Mirror of the events.db FTS schema owned by agent/core/events.py: an external-content FTS5 table
# fed by triggers that index json_extract(data, '$.text') for conversational events and
# json_extract(data, '$.summary') for the notifications carrying inbound messages.
_SCHEMA = """
CREATE TABLE events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, data TEXT NOT NULL);
CREATE VIRTUAL TABLE events_fts USING fts5(text_content, content='events', content_rowid='id');
CREATE TRIGGER events_fts_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, text_content)
    SELECT new.id, json_extract(new.data, '$.text')
    WHERE json_extract(new.data, '$.type') IN ('user', 'assistant', 'chat');
END;
CREATE TRIGGER events_fts_ai_notif AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, text_content)
    SELECT new.id, json_extract(new.data, '$.summary')
    WHERE json_extract(new.data, '$.type') = 'notification'
      AND COALESCE(json_extract(new.data, '$.source'), '') <> 'core'
      AND json_extract(new.data, '$.summary') IS NOT NULL;
END;
"""

Add = tp.Callable[..., None]


@pytest.fixture
def events_db(tmp_path: pathlib.Path) -> tp.Iterator[tuple[pathlib.Path, Add]]:
    path = tmp_path / "events.db"
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)

    def add(role: str, text: str, ts: str = "2026-01-01T00:00:00", source: str = "whatsapp") -> None:
        """Store one event in the shape its type has on disk: a notification carries its body in
        `summary` alongside the channel it came from, everything else carries `text`."""
        data = {"type": role, "source": source, "summary": text} if role == "notification" else {"type": role, "text": text}
        conn.execute("INSERT INTO events(ts, data) VALUES (?, ?)", (ts, json.dumps(data)))
        conn.commit()

    yield path, add
    conn.close()
