"""Tests for EventBus: emit, persist, pagination, search, lifecycle."""

import typing as tp

from core.events import ChatEvent, EventBus, SubagentStartEvent, UserEvent


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
