"""The recall skill's search query (mirrors EventBus.search over a real db)."""

import importlib.util
import pathlib

from core.events import AssistantEvent, EventBus, NotificationEvent


def _load_recall():
    path = pathlib.Path(__file__).resolve().parent.parent / "skills" / "recall" / "cli" / "src" / "recall_cli" / "cli.py"
    spec = importlib.util.spec_from_file_location("recall", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recall_finds_events_written_by_eventbus(tmp_path):
    bus = EventBus(data_dir=tmp_path)
    bus.emit(AssistantEvent(type="assistant", text="what is the weather in paris"))
    bus.emit(AssistantEvent(type="assistant", text="it is sunny in paris today"))
    bus.emit(AssistantEvent(type="assistant", text="how about london"))
    bus.close()

    recall = _load_recall()
    db_path = tmp_path / "events.db"
    results = recall.search(db_path, "paris", limit=20)
    assert len(results) == 2
    assert all("paris" in r["content"] for r in results)

    assert recall.search(db_path, "nonexistent", limit=20) == []
    assert recall.format_results([]) == "No results found."


def test_recall_returns_the_body_of_an_inbound_message(tmp_path):
    """An inbound message is stored as a notification whose body lives in `summary`, so recall reads
    content from there as well as from `text`: a hit with no content is the same as no hit."""
    bus = EventBus(data_dir=tmp_path)
    bus.emit(NotificationEvent(type="notification", source="whatsapp", summary="can you book the trip to seville"))
    bus.emit(AssistantEvent(type="assistant", text="she asked me to book something"))
    bus.close()

    recall = _load_recall()
    results = recall.search(tmp_path / "events.db", "seville", limit=20)

    assert len(results) == 1
    assert results[0]["role"] == "notification"
    assert results[0]["content"] == "can you book the trip to seville"
    assert "can you book the trip to seville" in recall.format_results(results)


def test_recall_missing_db_returns_empty(tmp_path):
    recall = _load_recall()
    assert recall.search(tmp_path / "nope.db", "anything", limit=20) == []
