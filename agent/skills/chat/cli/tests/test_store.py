"""Tests for the chat skill store: skill-assigned ids, oldest-to-newest paging with a cursor,
FTS5 search decayed toward recent, idempotent id-preserving import, the room every message is
filed under, and the node id a replicated message carries."""

import json
import sqlite3
import threading

import pytest
from chat_cli.store import Store, direct_room_id, store_path

_AGENT = "vesta"
_DIRECT_ROOM = direct_room_id(_AGENT)
_GROUP_ROOM = "room-7"

# The schema before rooms and node ids, pasted verbatim, so the upgrade is tested against the exact
# bytes an existing box carries.
_V1_SCHEMA = """
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


def _store(tmp_path) -> Store:
    return Store(store_path(tmp_path), _AGENT)


def _schema_version(tmp_path) -> int:
    conn = sqlite3.connect(str(store_path(tmp_path)))
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def test_append_assigns_incrementing_ids_and_pages_oldest_to_newest(tmp_path):
    store = _store(tmp_path)
    id1 = store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hi"})
    id2 = store.append({"type": "chat", "ts": "2026-01-01T00:00:01", "text": "hello"})

    assert (id1, id2) == (1, 2)
    events, cursor = store.page()
    assert cursor is None
    assert [(e["id"], e["type"], e["text"]) for e in events] == [(1, "user", "hi"), (2, "chat", "hello")]
    store.close()


def test_page_limit_and_cursor_walk_older(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.append({"type": "user", "ts": f"2026-01-01T00:00:0{i}", "text": f"m{i}"})

    page1, cursor1 = store.page(limit=2)
    assert [e["text"] for e in page1] == ["m3", "m4"]
    assert cursor1 == 4

    page2, cursor2 = store.page(limit=2, before_cursor=cursor1)
    assert [e["text"] for e in page2] == ["m1", "m2"]
    assert cursor2 == 2

    page3, cursor3 = store.page(limit=2, before_cursor=cursor2)
    assert [e["text"] for e in page3] == ["m0"]
    assert cursor3 is None
    store.close()


def test_page_returns_nothing_for_non_positive_limit(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hi"})
    assert store.page(limit=0) == ([], None)
    store.close()


def test_page_excludes_non_conversation_types(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hi"})
    store.append({"type": "tool_start", "ts": "2026-01-01T00:00:01", "text": "ran a tool"})

    events, _ = store.page()
    assert [e["type"] for e in events] == ["user"]
    store.close()


def test_search_matches_conversation_text(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "the quick brown fox"})
    store.append({"type": "chat", "ts": "2026-01-01T00:00:01", "text": "lazy dog sleeps"})

    results = store.search("fox")
    assert [e["text"] for e in results] == ["the quick brown fox"]
    store.close()


def test_search_favors_recent_matches(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2020-01-01T00:00:00", "text": "hello old"})
    store.append({"type": "user", "ts": "2026-07-01T00:00:00", "text": "hello new"})

    results = store.search("hello")
    assert results[0]["text"] == "hello new"
    store.close()


def test_search_malformed_query_raises_operational_error(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hi"})
    with pytest.raises(sqlite3.OperationalError):
        store.search('"unterminated')
    store.close()


def test_import_rows_preserves_ids_idempotently_and_indexes_fts(tmp_path):
    store = _store(tmp_path)
    rows = [
        (10, "2026-01-01T00:00:00", json.dumps({"type": "user", "text": "imported one"})),
        (20, "2026-01-01T00:00:01", json.dumps({"type": "chat", "text": "imported two"})),
    ]

    count, max_id = store.import_rows(rows)
    assert (count, max_id) == (2, 20)

    count2, _ = store.import_rows(rows)
    assert count2 == 0

    events, _ = store.page()
    assert [e["id"] for e in events] == [10, 20]
    assert [e["ts"] for e in events] == ["2026-01-01T00:00:00", "2026-01-01T00:00:01"]
    search_results = store.search("imported")
    assert [e["text"] for e in search_results]
    assert sorted(e["ts"] for e in search_results) == [
        "2026-01-01T00:00:00",
        "2026-01-01T00:00:01",
    ]
    store.close()


def test_bump_sequence_above_keeps_new_ids_above_imported(tmp_path):
    store = _store(tmp_path)
    store.import_rows([(100, "2026-01-01T00:00:00", json.dumps({"type": "user", "text": "old"}))])
    store.bump_sequence_above(100)

    new_id = store.append({"type": "user", "ts": "2026-01-01T00:00:02", "text": "new"})
    assert new_id > 100
    store.close()


def test_attachment_references_reads_structured_arrays_only(tmp_path):
    store = Store(store_path(tmp_path), _AGENT)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "hi", "attachments": [{"id": "abc123"}]})
    store.append({"type": "chat", "ts": "2026-01-02T00:00:00", "text": "the id is zzz999, quoted in plain text"})

    references = store.attachment_references()

    assert references == {"abc123": ("2026-01-01T00:00:00", "user")}
    assert "zzz999" not in references  # chat text quoting an id never pins a blob
    store.close()


def test_fresh_store_is_at_schema_version_two(tmp_path):
    store = _store(tmp_path)
    assert _schema_version(tmp_path) == 2
    store.close()


def test_v1_db_upgrades_to_v2_and_files_every_row_into_the_direct_room(tmp_path):
    """A db that predates rooms carries the conversation between the user and this agent, so the
    upgrade names it the direct room and paging, search and replication see one coherent history."""
    path = store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_SCHEMA)
    conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ("2026-01-01T00:00:00", json.dumps({"type": "user", "text": "old"})))
    conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ("2026-01-01T00:00:01", json.dumps({"type": "chat", "text": "older reply"})))
    conn.commit()
    conn.close()

    store = Store(path, _AGENT)

    assert _schema_version(tmp_path) == 2
    events, _ = store.page()
    assert [e["room"] for e in events] == [_DIRECT_ROOM, _DIRECT_ROOM]
    assert [e["text"] for e in events] == ["old", "older reply"]
    assert [e["text"] for e in store.search("old", room=_DIRECT_ROOM)] == ["old"]
    store.close()


def test_an_interrupted_v2_step_converges_on_the_next_open(tmp_path):
    """A box killed between the first added column and the version stamp must not brick its chat
    store: the next open finishes the step instead of failing on a duplicate column."""
    path = store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_SCHEMA)
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ("2026-01-01T00:00:00", json.dumps({"type": "user", "text": "half"})))
    conn.execute("ALTER TABLE events ADD COLUMN room TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()

    store = Store(path, _AGENT)
    store.close()

    assert _schema_version(tmp_path) == 2
    conn = sqlite3.connect(str(path))
    try:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(events)")}
    finally:
        conn.close()
    assert {"room", "node_id"} <= columns

    reopened = Store(path, _AGENT)
    events, _ = reopened.page()
    assert [(e["text"], e["room"]) for e in events] == [("half", _DIRECT_ROOM)]
    assert _schema_version(tmp_path) == 2
    reopened.close()


def test_the_v2_step_keeps_imported_ids_fts_and_the_sequence(tmp_path):
    """The upgrade must leave an imported history exactly as it was: the ids clients cached as
    cursors, the search index over them, and the sequence that keeps a new id above them."""
    path = store_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_SCHEMA)
    conn.execute("PRAGMA user_version = 1")
    insert = "INSERT INTO events (id, ts, data) VALUES (?, ?, ?)"
    conn.execute(insert, (100, "2026-01-01T00:00:00", json.dumps({"type": "user", "text": "keel"})))
    conn.execute(insert, (101, "2026-01-01T00:00:01", json.dumps({"type": "chat", "text": "keel yes"})))
    conn.commit()
    conn.close()

    store = Store(path, _AGENT)

    events, _ = store.page()
    assert [e["id"] for e in events] == [100, 101]
    assert sorted(e["id"] for e in store.search("keel")) == [100, 101]
    assert store.append({"type": "chat", "ts": "2026-01-01T00:00:02", "text": "after"}) == 102
    store.close()


def test_a_node_id_is_unique_across_rows(tmp_path):
    """Two rows must never claim the same node message: the replica asks `has_node_id` first, and a
    bug that skips the question fails loudly here instead of duplicating a message."""
    store = _store(tmp_path)
    first = store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "one"})
    second = store.append({"type": "chat", "ts": "2026-01-01T00:00:01", "text": "two"})
    store.mark_node_id(first, 7)

    with pytest.raises(sqlite3.IntegrityError):
        store.mark_node_id(second, 7)
    store.close()


def test_append_files_a_roomless_event_into_the_direct_room(tmp_path):
    store = _store(tmp_path)
    event = {"type": "user", "ts": "2026-01-01T00:00:00", "text": "hi"}
    store.append(event)

    assert event["room"] == _DIRECT_ROOM
    events, _ = store.page()
    assert [e["room"] for e in events] == [_DIRECT_ROOM]
    store.close()


def test_room_and_node_id_ride_columns_not_the_json_blob(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "chat", "ts": "2026-01-01T00:00:00", "text": "hey", "room": _GROUP_ROOM, "node_id": 44})

    conn = sqlite3.connect(str(store_path(tmp_path)))
    try:
        room, node_id, data = conn.execute("SELECT room, node_id, data FROM events WHERE id = 1").fetchone()
    finally:
        conn.close()
    assert (room, node_id) == (_GROUP_ROOM, 44)
    assert "room" not in json.loads(data)
    assert "node_id" not in json.loads(data)
    store.close()


def test_mark_node_id_makes_a_row_known_to_the_node(tmp_path):
    store = _store(tmp_path)
    local_id = store.append({"type": "chat", "ts": "2026-01-01T00:00:00", "text": "sent"})

    assert store.has_node_id(91) is False
    assert store.max_node_id(_DIRECT_ROOM) == 0

    store.mark_node_id(local_id, 91)

    assert store.has_node_id(91) is True
    assert store.max_node_id(_DIRECT_ROOM) == 91
    assert store.max_node_id(_GROUP_ROOM) == 0
    events, _ = store.page()
    assert events[0]["node_id"] == 91
    store.close()


def test_max_node_id_is_per_room(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "a", "node_id": 5})
    store.append({"type": "user", "ts": "2026-01-01T00:00:01", "text": "b", "room": _GROUP_ROOM, "node_id": 12})

    assert store.max_node_id(_DIRECT_ROOM) == 5
    assert store.max_node_id(_GROUP_ROOM) == 12
    store.close()


def test_page_filters_by_room(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "to me"})
    store.append({"type": "user", "ts": "2026-01-01T00:00:01", "text": "to the group", "room": _GROUP_ROOM})

    group, cursor = store.page(room=_GROUP_ROOM)
    assert cursor is None
    assert [e["text"] for e in group] == ["to the group"]
    direct, _ = store.page(room=_DIRECT_ROOM)
    assert [e["text"] for e in direct] == ["to me"]
    everything, _ = store.page()
    assert [e["text"] for e in everything] == ["to me", "to the group"]
    store.close()


def test_search_filters_by_room(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "harbour plans"})
    store.append({"type": "user", "ts": "2026-01-01T00:00:01", "text": "harbour weather", "room": _GROUP_ROOM})

    assert [e["text"] for e in store.search("harbour", room=_GROUP_ROOM)] == ["harbour weather"]
    assert [e["text"] for e in store.search("harbour", room=_DIRECT_ROOM)] == ["harbour plans"]
    assert len(store.search("harbour")) == 2
    store.close()


def test_unsynced_direct_rows_skips_synced_rows_and_other_rooms(tmp_path):
    store = _store(tmp_path)
    store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "waiting"})
    already = store.append({"type": "chat", "ts": "2026-01-01T00:00:01", "text": "landed"})
    store.mark_node_id(already, 3)
    store.append({"type": "user", "ts": "2026-01-01T00:00:02", "text": "elsewhere", "room": _GROUP_ROOM})
    store.append({"type": "tool_start", "ts": "2026-01-01T00:00:03", "text": "ran a tool"})

    assert [e["text"] for e in store.unsynced_direct_rows()] == ["waiting"]
    store.close()


def test_local_id_for_origin_maps_an_imported_message_back(tmp_path):
    store = _store(tmp_path)
    local_id = store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": "mine"})

    assert store.local_id_for_origin(_DIRECT_ROOM, local_id) == local_id
    assert store.local_id_for_origin(_GROUP_ROOM, local_id) is None
    assert store.local_id_for_origin(_DIRECT_ROOM, local_id + 99) is None
    store.close()


def test_rooms_round_trip_through_upsert_read_and_delete(tmp_path):
    store = _store(tmp_path)
    store.upsert_room({"id": "room-1", "name": "Sailing", "agents": ["vesta", "bob"]})
    store.upsert_room({"id": "room-2", "name": None, "agents": ["vesta", "ada"]})

    assert store.rooms() == [
        {"id": "room-1", "name": "Sailing", "agents": ["vesta", "bob"]},
        {"id": "room-2", "name": None, "agents": ["vesta", "ada"]},
    ]
    assert store.room("room-2") == {"id": "room-2", "name": None, "agents": ["vesta", "ada"]}
    assert store.room("room-9") is None

    store.upsert_room({"id": "room-1", "name": "Sailing plans", "agents": ["vesta"]})
    assert store.room("room-1") == {"id": "room-1", "name": "Sailing plans", "agents": ["vesta"]}

    store.delete_room("room-1")
    assert [record["id"] for record in store.rooms()] == ["room-2"]
    store.delete_room("room-1")  # deleting what is already gone is a no-op
    store.close()


def test_import_rows_files_core_history_into_the_direct_room(tmp_path):
    store = _store(tmp_path)
    store.import_rows([(7, "2026-01-01T00:00:00", json.dumps({"type": "user", "text": "from core"}))])

    events, _ = store.page(room=_DIRECT_ROOM)
    assert [e["text"] for e in events] == ["from core"]
    assert [e["text"] for e in store.unsynced_direct_rows()] == ["from core"]
    store.close()


def test_appends_from_two_threads_both_land(tmp_path):
    """The daemon appends from its own loop while the replica appends from a worker thread, so the one
    writer connection is shared across threads and every use of it is serialized by the store's lock."""
    store = _store(tmp_path)
    written = [f"{name}-{index}" for name in ("one", "two") for index in range(20)]

    def append(name: str) -> None:
        for index in range(20):
            store.append({"type": "user", "ts": "2026-01-01T00:00:00", "text": f"{name}-{index}"})

    threads = [threading.Thread(target=append, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    events, _ = store.page(limit=100, room=_DIRECT_ROOM)
    assert sorted(event["text"] for event in events) == sorted(written)
    store.close()
