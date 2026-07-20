"""Tests for the app-chat skill store: skill-assigned ids, oldest-to-newest paging with a cursor,
FTS5 search decayed toward recent, and idempotent id-preserving import."""

import json
import sqlite3

import pytest
from app_chat_cli.store import Store, store_path


def _store(tmp_path) -> Store:
    return Store(store_path(tmp_path))


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
    assert [e["text"] for e in store.search("imported")]
    store.close()


def test_bump_sequence_above_keeps_new_ids_above_imported(tmp_path):
    store = _store(tmp_path)
    store.import_rows([(100, "2026-01-01T00:00:00", json.dumps({"type": "user", "text": "old"}))])
    store.bump_sequence_above(100)

    new_id = store.append({"type": "user", "ts": "2026-01-01T00:00:02", "text": "new"})
    assert new_id > 100
    store.close()
