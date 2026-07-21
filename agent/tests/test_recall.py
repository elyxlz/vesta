"""The recall skill's search query (mirrors EventBus.search over a real db)."""

import importlib.util
import pathlib

from core.events import AssistantEvent, EventBus


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


def test_recall_missing_db_returns_empty(tmp_path):
    recall = _load_recall()
    assert recall.search(tmp_path / "nope.db", "anything", limit=20) == []
