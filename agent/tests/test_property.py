"""Property-based tests (hypothesis): EventBus round-trips and FTS5 search robustness.

These complement the example-based tests in test_contract.py and test_eventbus.py by
generating adversarial inputs (unicode edge cases, FTS5 metacharacters, control chars)
that nobody thinks to write by hand.
"""

import pathlib as pl
import sqlite3
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from core.events import (
    AssistantEvent,
    ErrorEvent,
    EventBus,
    NotificationEvent,
    ThinkingEvent,
)

# st.text() already excludes lone surrogates (category Cs), matching reality: event text
# arrives via JSON / UTF-8, which cannot carry them.
EVENT_TEXT = st.text(max_size=500)


@settings(max_examples=50, deadline=None)
@given(text=EVENT_TEXT)
def test_text_events_roundtrip_exactly(text):
    """Any UTF-8 text survives emit -> SQLite -> recent() byte for byte, for every persisted
    text-bearing event type (user/chat are live-only and never persisted, so excluded)."""
    with tempfile.TemporaryDirectory() as tmp:
        bus = EventBus(data_dir=pl.Path(tmp))
        try:
            bus.emit(AssistantEvent(type="assistant", text=text))
            bus.emit(ThinkingEvent(type="thinking", text=text, signature=text))
            bus.emit(ErrorEvent(type="error", text=text))
            bus.emit(NotificationEvent(type="notification", source=text, summary=text))

            stored, _ = bus.recent(limit=10)
            # dict() copies narrow the TypedDict union to plain dicts so per-type keys can be indexed.
            by_type = {e["type"]: dict(e) for e in stored}
            assert by_type["assistant"]["text"] == text
            assert by_type["thinking"]["text"] == text
            assert by_type["thinking"]["signature"] == text
            assert by_type["error"]["text"] == text
            assert by_type["notification"]["source"] == text
            assert by_type["notification"]["summary"] == text
        finally:
            bus.close()


@settings(max_examples=100, deadline=None)
@given(query=st.text(max_size=200))
def test_search_never_corrupts_the_bus(query):
    """search() with arbitrary raw input either returns results or raises sqlite3.Error
    (both callers catch it: api.py returns 400, tools.py returns an error message).
    Whatever happens, the bus must keep working afterwards."""
    with tempfile.TemporaryDirectory() as tmp:
        bus = EventBus(data_dir=pl.Path(tmp))
        try:
            bus.emit(ErrorEvent(type="error", text="the quick brown fox"))

            search_failed = False
            try:
                results = bus.search(query)
            except sqlite3.Error:
                search_failed = True
            if not search_failed:
                assert isinstance(results, list)

            bus.emit(AssistantEvent(type="assistant", text="jumped over the lazy dog"))
            stored, _ = bus.recent(limit=2)
            assert [e["type"] for e in stored] == ["error", "assistant"]
        finally:
            bus.close()


@settings(max_examples=100, deadline=None)
@given(query=st.text(min_size=1, max_size=200).filter(lambda s: "\x00" not in s))
def test_search_with_phrase_quoting_never_raises(query):
    """FTS5 phrase-quoting (escape inner quotes, wrap in quotes) makes any null-free string
    a valid query. This is the pattern callers can rely on for raw user input."""
    with tempfile.TemporaryDirectory() as tmp:
        bus = EventBus(data_dir=pl.Path(tmp))
        try:
            bus.emit(AssistantEvent(type="assistant", text="hello world"))
            quoted = '"' + query.replace('"', '""') + '"'
            results = bus.search(quoted)
            assert isinstance(results, list)
        finally:
            bus.close()
