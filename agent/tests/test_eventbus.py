"""Tests for EventBus: emit, persist, pagination, search, lifecycle, schema migration."""

import sqlite3
import typing as tp

from core.events import (
    _EVENTS_SCHEMA,
    _SCHEMA_VERSION,
    SUBSCRIBER_QUEUE_MAXSIZE,
    ChatEvent,
    EventBus,
    NotificationEvent,
    SubagentStartEvent,
    ToolStartEvent,
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
    """All non-status event types are persisted."""
    event_bus.emit(ChatEvent(type="chat", text="hello"))
    event_bus.emit(SubagentStartEvent(type="subagent_start", agent_id="a", agent_type="browser"))

    events, _ = event_bus.recent()
    types = {e["type"] for e in events}
    assert "chat" in types
    assert "subagent_start" in types


def test_status_not_persisted(event_bus):
    """Status events are broadcast to subscribers but not stored."""
    q = event_bus.subscribe()
    event_bus.set_state("thinking")
    received = q.get_nowait()
    assert received["type"] == "status"

    events, _ = event_bus.recent()
    assert len(events) == 0


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
    bus.emit(UserEvent(type="user", text="before restart"))
    bus.emit(ChatEvent(type="chat", text="reply"))
    bus.close()

    bus2 = EventBus(data_dir=tmp_path)
    events, _ = bus2.recent()
    texts = [tp.cast(tp.Any, e)["text"] for e in events if "text" in e]
    assert "before restart" in texts
    assert "reply" in texts
    bus2.close()


# --- Backpressure ---


def test_slow_subscriber_queue_is_bounded(event_bus):
    """A subscriber that never drains stays bounded; the oldest events are dropped."""
    q = event_bus.subscribe()
    overflow = 50
    total = SUBSCRIBER_QUEUE_MAXSIZE + overflow
    for i in range(total):
        event_bus.emit(UserEvent(type="user", text=f"msg {i}"))

    assert q.qsize() == SUBSCRIBER_QUEUE_MAXSIZE

    drained = [q.get_nowait() for _ in range(q.qsize())]
    texts = [tp.cast(tp.Any, e)["text"] for e in drained]
    # Oldest `overflow` events were evicted; the queue holds the most recent window.
    assert texts[0] == f"msg {overflow}"
    assert texts[-1] == f"msg {total - 1}"


def test_drop_does_not_affect_other_subscribers(event_bus):
    """Overflowing one subscriber must not drop events for a healthy one."""
    slow = event_bus.subscribe()
    fast = event_bus.subscribe()
    total = SUBSCRIBER_QUEUE_MAXSIZE + 10
    for i in range(total):
        event = UserEvent(type="user", text=f"msg {i}")
        event_bus.emit(event)
        fast.get_nowait()  # fast subscriber keeps draining, never overflows

    assert slow.qsize() == SUBSCRIBER_QUEUE_MAXSIZE
    assert fast.qsize() == 0


# --- Pagination ---


def test_recent_pagination(event_bus):
    """recent() returns last N events and a cursor when there are more."""
    for i in range(150):
        event_bus.emit(UserEvent(type="user", text=f"msg {i}"))

    events, cursor = event_bus.recent(limit=50)
    assert len(events) == 50
    assert tp.cast(tp.Any, events[-1])["text"] == "msg 149"
    assert tp.cast(tp.Any, events[0])["text"] == "msg 100"
    assert cursor is not None


def test_cursor_pagination(event_bus):
    """before(cursor) returns the previous page of events."""
    for i in range(80):
        event_bus.emit(UserEvent(type="user", text=f"msg {i}"))

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


def test_app_chat_channel_filters_out_noise(event_bus):
    """recent(channel="app-chat") keeps the conversation even when notifications and
    hidden-by-default tool calls flood the recent window — the regression that blanked
    the chat, then left only a handful of messages once tool_start counted toward the cap."""
    event_bus.emit(UserEvent(type="user", text="my real message"))
    event_bus.emit(ChatEvent(type="chat", text="my real reply"))
    for i in range(200):
        event_bus.emit(NotificationEvent(type="notification", source="core", summary=f"spam {i}"))
        event_bus.emit(ToolStartEvent(type="tool_start", tool="Bash", input=f"cmd {i}", subagent=False))

    events, _ = event_bus.recent(limit=50, channel="app-chat")
    types = {tp.cast(tp.Any, e)["type"] for e in events}
    assert types == {"user", "chat"}
    texts = [tp.cast(tp.Any, e)["text"] for e in events]
    assert texts == ["my real message", "my real reply"]

    # Unfiltered recent() still returns the raw tail (other consumers untouched): here
    # it is all noise, which is exactly why the conversation needs the channel filter.
    raw, _ = event_bus.recent(limit=50)
    raw_types = {tp.cast(tp.Any, e)["type"] for e in raw}
    assert raw_types == {"notification", "tool_start"}


def test_app_chat_channel_paginates_across_notification_runs(event_bus):
    """before(cursor, channel) skips notification noise between conversation pages."""
    for i in range(5):
        event_bus.emit(UserEvent(type="user", text=f"msg {i}"))
        for j in range(20):
            event_bus.emit(NotificationEvent(type="notification", source="core", summary=f"noise {i}-{j}"))

    page, cursor = event_bus.recent(limit=3, channel="app-chat")
    assert [tp.cast(tp.Any, e)["text"] for e in page] == ["msg 2", "msg 3", "msg 4"]
    assert cursor is not None

    older, cursor2 = event_bus.before(cursor, limit=3, channel="app-chat")
    assert [tp.cast(tp.Any, e)["text"] for e in older] == ["msg 0", "msg 1"]
    assert cursor2 is None


# --- Search ---


def test_search(event_bus):
    """EventBus.search() finds text-bearing events via FTS5."""
    event_bus.emit(UserEvent(type="user", text="what is the weather in paris"))
    event_bus.emit(ChatEvent(type="chat", text="it is sunny in paris today"))
    event_bus.emit(UserEvent(type="user", text="how about london"))
    event_bus.emit(ChatEvent(type="chat", text="london is rainy as usual"))

    results = event_bus.search("paris")
    assert len(results) == 2
    assert any("paris" in r["content"] for r in results)

    results = event_bus.search("london")
    assert len(results) == 2

    results = event_bus.search("sunny")
    assert len(results) == 1
    assert results[0]["role"] == "chat"


def test_search_no_results(event_bus):
    event_bus.emit(UserEvent(type="user", text="hello world"))
    assert event_bus.search("nonexistent") == []


def test_search_limit(event_bus):
    for i in range(10):
        event_bus.emit(UserEvent(type="user", text=f"message number {i} about python"))
    results = event_bus.search("python", limit=3)
    assert len(results) == 3


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
