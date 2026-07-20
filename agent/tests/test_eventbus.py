"""Tests for EventBus: emit, persist, pagination, search, lifecycle, schema migration."""

import json
import sqlite3
import typing as tp

import pytest

from core.events import (
    _EVENTS_SCHEMA,
    _SCHEMA_VERSION,
    SUBSCRIBER_QUEUE_MAXSIZE,
    AssistantEvent,
    ChatEvent,
    EventBus,
    NotificationClearedEvent,
    SubagentStartEvent,
    UserEvent,
)

# --- Emit & persist ---


def test_emit_subagent_start(event_bus):
    q = event_bus.subscribe()
    event = SubagentStartEvent(type="subagent_start", agent_id="abc", agent_type="browser")
    event_bus.emit(event)
    received = q.get_nowait()
    assert received["type"] == "subagent_start"
    assert received["agent_id"] == "abc"
    assert received["agent_type"] == "browser"
    events, _ = event_bus.recent()
    assert len(events) == 1
    assert events[0]["type"] == "subagent_start"


def test_all_types_persisted(event_bus):
    """Event types outside the live-only set are persisted."""
    event_bus.emit(AssistantEvent(type="assistant", text="hello"))
    event_bus.emit(SubagentStartEvent(type="subagent_start", agent_id="a", agent_type="browser"))

    events, _ = event_bus.recent()
    types = {e["type"] for e in events}
    assert "assistant" in types
    assert "subagent_start" in types


def test_status_not_persisted(event_bus):
    """Status events are broadcast to subscribers but not stored."""
    q = event_bus.subscribe()
    event_bus.set_state("thinking")
    received = q.get_nowait()
    assert received["type"] == "status"

    events, _ = event_bus.recent()
    assert len(events) == 0


def test_user_and_chat_are_live_only(event_bus):
    """user and chat are broadcast transport only now (the app-chat skill owns their durability): they
    reach subscribers but are never persisted to events.db."""
    q = event_bus.subscribe()
    event_bus.emit(UserEvent(type="user", text="a message"))
    event_bus.emit(ChatEvent(type="chat", text="a reply"))
    assert q.get_nowait()["type"] == "user"
    assert q.get_nowait()["type"] == "chat"
    events, _ = event_bus.recent()
    assert events == []


def test_emit_preformed_broadcasts_without_persisting(event_bus):
    """emit_preformed pushes a skill's fully-formed event to every subscriber verbatim: its
    skill-assigned positive id and ts pass straight through, and nothing is persisted."""
    q = event_bus.subscribe()
    event_bus.emit_preformed(ChatEvent(type="chat", id=42, ts="2026-01-01T00:00:00+00:00", text="from the skill"))
    received = q.get_nowait()
    assert received["id"] == 42
    assert received["ts"] == "2026-01-01T00:00:00+00:00"
    assert received["text"] == "from the skill"
    events, _ = event_bus.recent()
    assert events == []


def test_emit_survives_history_write_failure(event_bus):
    """A failed history write never crashes the emitting coroutine: any sqlite3.Error (a closed or
    corrupt db, not only a locked one) drops the row with a warning and live subscribers still
    receive the event."""
    q = event_bus.subscribe()
    event_bus._conn.close()
    event_bus.emit(AssistantEvent(type="assistant", text="still delivered"))
    assert q.get_nowait()["text"] == "still delivered"


def test_no_data_dir():
    """EventBus works without persistence (no data_dir)."""
    bus = EventBus()
    q = bus.subscribe()
    bus.emit(UserEvent(type="user", text="hello"))
    received = q.get_nowait()
    assert received["type"] == "user"
    events, _ = bus.recent()
    assert events == []
    bus.close()


def test_persists_across_instances(tmp_path):
    """Events survive EventBus recreation (simulating container restart)."""
    bus = EventBus(data_dir=tmp_path)
    bus.emit(AssistantEvent(type="assistant", text="before restart"))
    bus.emit(AssistantEvent(type="assistant", text="reply"))
    bus.close()

    bus2 = EventBus(data_dir=tmp_path)
    events, _ = bus2.recent()
    texts = [tp.cast(tp.Any, e)["text"] for e in events if "text" in e]
    assert "before restart" in texts
    assert "reply" in texts
    bus2.close()


# --- Backpressure ---


def test_stalled_subscriber_is_evicted_on_overflow(event_bus):
    """A subscriber that stops draining is evicted at its first overflow: the stale backlog is
    replaced by a single EvictedEvent telling the send loop to close (the client reconnects and
    resyncs from the connect snapshot), and further emits no longer reach it. A subscriber
    either receives every event or gets a clean disconnect; nothing is dropped silently
    (regression: issue #1160's unbounded drop-oldest storm)."""
    q = event_bus.subscribe()
    for i in range(SUBSCRIBER_QUEUE_MAXSIZE + 1):
        event_bus.emit(UserEvent(type="user", text=f"msg {i}"))

    assert q.qsize() == 1
    assert q.get_nowait()["type"] == "evicted"

    event_bus.emit(UserEvent(type="user", text="after eviction"))
    assert q.qsize() == 0


def test_eviction_logs_one_warning_not_a_storm(event_bus, caplog):
    """The overflow storm is coalesced: a stalled subscriber produces exactly one warning at
    eviction, no matter how many events keep flowing afterwards, not one line per event."""
    q = event_bus.subscribe()
    with caplog.at_level("WARNING", logger="vesta.events"):
        for i in range(SUBSCRIBER_QUEUE_MAXSIZE + 200):
            event_bus.emit(UserEvent(type="user", text=f"msg {i}"))

    assert q.qsize() == 1  # the sentinel; the post-eviction flood never reached it
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1


def test_eviction_does_not_affect_other_subscribers(event_bus):
    """Evicting an overflowing subscriber must not drop events for a healthy one."""
    slow = event_bus.subscribe()
    fast = event_bus.subscribe()
    total = SUBSCRIBER_QUEUE_MAXSIZE + 10
    delivered = []
    for i in range(total):
        event_bus.emit(UserEvent(type="user", text=f"msg {i}"))
        delivered.append(tp.cast(tp.Any, fast.get_nowait())["text"])  # fast keeps draining

    assert delivered == [f"msg {i}" for i in range(total)]
    assert slow.qsize() == 1
    assert slow.get_nowait()["type"] == "evicted"


def test_draining_subscriber_is_never_evicted(event_bus):
    """A subscriber that keeps draining, even one that hovers at the queue bound, receives
    every event and is never evicted."""
    q = event_bus.subscribe()
    for i in range(SUBSCRIBER_QUEUE_MAXSIZE):
        event_bus.emit(UserEvent(type="user", text=f"fill {i}"))
    for i in range(50):
        q.get_nowait()  # make one slot of room
        event_bus.emit(UserEvent(type="user", text=f"paced {i}"))

    assert q.qsize() == SUBSCRIBER_QUEUE_MAXSIZE
    drained = [tp.cast(tp.Any, q.get_nowait())["text"] for _ in range(q.qsize())]
    assert drained[-1] == "paced 49"
    event_bus.emit(UserEvent(type="user", text="still subscribed"))
    assert tp.cast(tp.Any, q.get_nowait())["text"] == "still subscribed"


# --- Pagination ---


def test_recent_pagination(event_bus):
    """recent() returns last N events and a cursor when there are more."""
    for i in range(150):
        event_bus.emit(AssistantEvent(type="assistant", text=f"msg {i}"))

    events, cursor = event_bus.recent(limit=50)
    assert len(events) == 50
    assert tp.cast(tp.Any, events[-1])["text"] == "msg 149"
    assert tp.cast(tp.Any, events[0])["text"] == "msg 100"
    assert cursor is not None


def test_cursor_pagination(event_bus):
    """before(cursor) returns the previous page of events."""
    for i in range(80):
        event_bus.emit(AssistantEvent(type="assistant", text=f"msg {i}"))

    events, cursor = event_bus.recent(limit=30)
    assert len(events) == 30
    assert cursor is not None

    older, cursor2 = event_bus.before(cursor, limit=30)
    assert len(older) == 30
    assert tp.cast(tp.Any, older[-1])["text"] == "msg 49"
    assert tp.cast(tp.Any, older[0])["text"] == "msg 20"
    assert cursor2 is not None

    oldest, cursor3 = event_bus.before(cursor2, limit=30)
    assert len(oldest) == 20
    assert tp.cast(tp.Any, oldest[0])["text"] == "msg 0"
    assert cursor3 is None


def test_recent_runs_off_the_connection_home_thread(event_bus):
    """History reads must work from a worker thread so api.py can offload them via
    asyncio.to_thread — a slow scan then never blocks the event loop (which would starve
    vestad's status poll and flap the agent to 'starting'). A connection bound to one
    thread raises sqlite3.ProgrammingError here; to_thread uses exactly such a pool."""
    import concurrent.futures

    event_bus.emit(AssistantEvent(type="assistant", text="hi"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        events, _ = pool.submit(event_bus.recent).result()
    assert [tp.cast(tp.Any, e)["text"] for e in events] == ["hi"]


# --- Search ---


def test_search(event_bus):
    """EventBus.search() finds text-bearing events via FTS5."""
    event_bus.emit(AssistantEvent(type="assistant", text="what is the weather in paris"))
    event_bus.emit(AssistantEvent(type="assistant", text="it is sunny in paris today"))
    event_bus.emit(AssistantEvent(type="assistant", text="how about london"))
    event_bus.emit(AssistantEvent(type="assistant", text="london is rainy as usual"))

    results = event_bus.search("paris")
    assert len(results) == 2
    assert any("paris" in r["text"] for r in results)

    results = event_bus.search("london")
    assert len(results) == 2

    results = event_bus.search("sunny")
    assert len(results) == 1
    assert results[0]["type"] == "assistant"


def test_search_no_results(event_bus):
    event_bus.emit(AssistantEvent(type="assistant", text="hello world"))
    assert event_bus.search("nonexistent") == []


def test_search_limit(event_bus):
    for i in range(10):
        event_bus.emit(AssistantEvent(type="assistant", text=f"message number {i} about python"))
    results = event_bus.search("python", limit=3)
    assert len(results) == 3


def test_search_runs_off_the_connection_home_thread(event_bus):
    """Like recent(), search() must work from a worker thread so /history can offload it via
    asyncio.to_thread — an FTS MATCH over a years-old db must never block the event loop or
    interleave with emit's writer-connection transactions. A connection bound to one thread
    raises sqlite3.ProgrammingError here; to_thread uses exactly such a pool."""
    import concurrent.futures

    event_bus.emit(AssistantEvent(type="assistant", text="what is the weather in paris"))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        results = pool.submit(event_bus.search, "paris").result()
    assert len(results) == 1
    assert results[0]["text"] == "what is the weather in paris"


# --- Schema migration ---


def _db_user_version(tmp_path) -> int:
    conn = sqlite3.connect(str(tmp_path / "events.db"))
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def test_fresh_db_stamped_to_current_version(tmp_path):
    """A fresh events.db ends at the current schema version."""
    bus = EventBus(data_dir=tmp_path)
    bus.close()
    assert _db_user_version(tmp_path) == _SCHEMA_VERSION


def test_pre_versioned_db_upgraded_in_place(tmp_path):
    """A pre-versioned db (tables present, user_version=0) is stamped to v1 without data loss."""
    conn = sqlite3.connect(str(tmp_path / "events.db"))
    conn.executescript(_EVENTS_SCHEMA)
    conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ("2026-01-01T00:00:00+00:00", '{"type": "user", "text": "legacy"}'))
    conn.commit()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 0
    conn.close()

    bus = EventBus(data_dir=tmp_path)
    events, _ = bus.recent()
    bus.close()

    assert _db_user_version(tmp_path) == _SCHEMA_VERSION
    assert len(events) == 1
    assert tp.cast(tp.Any, events[0])["text"] == "legacy"


def test_corrupt_db_is_quarantined_and_boots_fresh(tmp_path):
    """A corrupt events.db (disk-full mid-write, bit rot, a restored hot backup) must not
    crash-loop the container: it is renamed aside intact and the agent boots with empty history."""
    db_path = tmp_path / "events.db"
    original_bytes = b"not a sqlite database, just garbage bytes overwriting a once-valid file"
    db_path.write_bytes(original_bytes)

    bus = EventBus(data_dir=tmp_path)
    try:
        events, _ = bus.recent()
        assert events == []

        bus.emit(AssistantEvent(type="assistant", text="alive after recovery"))
        events, _ = bus.recent()
        assert len(events) == 1
        assert tp.cast(tp.Any, events[0])["text"] == "alive after recovery"
    finally:
        bus.close()

    assert db_path.exists(), "a fresh events.db must exist after quarantine"
    quarantined = list(tmp_path.glob("events.db.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == original_bytes


def test_transient_open_error_propagates_without_quarantine(tmp_path):
    """A transient OperationalError at boot (locked, disk full, IO error) is not corruption:
    it must crash for Docker's on-failure retry, never quarantine the healthy db."""
    db_path = tmp_path / "events.db"
    bus = EventBus(data_dir=tmp_path)
    bus.emit(AssistantEvent(type="assistant", text="precious history"))
    bus.close()
    original_bytes = db_path.read_bytes()

    db_path.chmod(0o444)
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(sqlite3.OperationalError):
            EventBus(data_dir=tmp_path)
    finally:
        tmp_path.chmod(0o755)
        db_path.chmod(0o644)

    assert db_path.read_bytes() == original_bytes
    assert list(tmp_path.glob("events.db.corrupt-*")) == []


# --- Event ids ---


def test_emit_stamps_rowid_as_id(event_bus):
    """A persisted event carries its events.db rowid as a positive, stable id on both the live
    broadcast and the history read-back (same id from both paths)."""
    q = event_bus.subscribe()
    event_bus.emit(AssistantEvent(type="assistant", text="first"))
    live = q.get_nowait()
    assert live["id"] == 1
    stored, _ = event_bus.recent()
    assert stored[0]["id"] == 1


def test_ids_track_rowid_in_order(event_bus):
    for i in range(3):
        event_bus.emit(AssistantEvent(type="assistant", text=f"m{i}"))
    stored, _ = event_bus.recent()
    assert [e["id"] for e in stored] == [1, 2, 3]


def test_id_is_not_stored_in_the_data_blob(event_bus):
    """id is derived from the rowid, never persisted into the JSON blob, so legacy rows stay valid."""
    event_bus.emit(AssistantEvent(type="assistant", text="hi"))
    row = event_bus._conn.execute("SELECT data FROM events").fetchone()
    assert "id" not in json.loads(row[0])


def test_live_only_events_get_negative_ids(event_bus):
    """The live-only types (status, notification_cleared, user, chat) skip persistence but still carry
    an id: a per-session counter running negative, which can never collide with a positive rowid."""
    q = event_bus.subscribe()
    event_bus.set_state("thinking")
    first = q.get_nowait()
    assert first["type"] == "status"
    assert first["id"] == -1
    event_bus.emit(NotificationClearedEvent(type="notification_cleared", notif_id="x"))
    assert q.get_nowait()["id"] == -2
    event_bus.emit(UserEvent(type="user", text="hi"))
    assert q.get_nowait()["id"] == -3
    event_bus.emit(ChatEvent(type="chat", text="yo"))
    assert q.get_nowait()["id"] == -4


def test_legacy_row_without_id_gets_rowid_on_read(tmp_path):
    """A pre-existing row whose blob predates ids gains an id from its rowid on read: ids are
    derived, so no schema migration is needed."""
    conn = sqlite3.connect(str(tmp_path / "events.db"))
    conn.executescript(_EVENTS_SCHEMA)
    conn.execute("INSERT INTO events (ts, data) VALUES (?, ?)", ("2026-01-01T00:00:00+00:00", '{"type": "user", "text": "legacy"}'))
    conn.commit()
    conn.close()

    bus = EventBus(data_dir=tmp_path)
    events, _ = bus.recent()
    bus.close()
    assert events[0]["id"] == 1
    assert tp.cast(tp.Any, events[0])["text"] == "legacy"


def test_recent_and_search_reads_carry_ids(event_bus):
    event_bus.emit(AssistantEvent(type="assistant", text="weather in paris"))
    event_bus.emit(AssistantEvent(type="assistant", text="sunny in paris"))
    recent, _ = event_bus.recent()
    assert all(e["id"] > 0 for e in recent)
    results = event_bus.search("paris")
    assert all(e["id"] > 0 for e in results)


def test_emit_without_persistence_still_ids(event_bus):
    """When a history write is dropped (closed/corrupt db), the event still broadcasts and still
    gets a live id, never a bare event with no id."""
    q = event_bus.subscribe()
    event_bus._conn.close()
    event_bus.emit(AssistantEvent(type="assistant", text="still delivered"))
    delivered = q.get_nowait()
    assert delivered["text"] == "still delivered"
    assert delivered["id"] < 0
