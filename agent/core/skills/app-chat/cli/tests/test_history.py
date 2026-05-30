"""Tests for `app-chat history` recent-message paging (no --search)."""

import app_chat_cli.commands as commands


def _make_api_get(pages: list[dict[str, object]], calls: list[dict[str, str]]):
    def fake(base_url: str, path: str, params: dict[str, str]) -> dict[str, object]:
        calls.append(params)
        return pages[len(calls) - 1]

    return fake


def test_recent_messages_returns_last_n_messages(monkeypatch):
    events: list[object] = [{"ts": f"t{i}", "type": "user", "text": f"m{i}"} for i in range(5)]
    page: dict[str, object] = {"events": events, "cursor": None}
    monkeypatch.setattr(commands, "_api_get", _make_api_get([page], []))

    result = commands._recent_messages("http://x", 3)

    assert result == [
        {"timestamp": "t2", "role": "user", "content": "m2"},
        {"timestamp": "t3", "role": "user", "content": "m3"},
        {"timestamp": "t4", "role": "user", "content": "m4"},
    ]


def test_recent_messages_pages_past_non_message_events(monkeypatch):
    page1: dict[str, object] = {
        "events": [
            {"ts": "t5", "type": "tool_start", "tool": "x"},
            {"ts": "t6", "type": "tool_end", "tool": "x"},
        ],
        "cursor": 10,
    }
    page2: dict[str, object] = {
        "events": [
            {"ts": "t1", "type": "user", "text": "hello"},
            {"ts": "t2", "type": "assistant", "text": "hi"},
        ],
        "cursor": None,
    }
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(commands, "_api_get", _make_api_get([page1, page2], calls))

    result = commands._recent_messages("http://x", 2)

    assert result == [
        {"timestamp": "t1", "role": "user", "content": "hello"},
        {"timestamp": "t2", "role": "assistant", "content": "hi"},
    ]
    assert calls[1]["cursor"] == "10"


def test_recent_messages_stops_when_no_older_events(monkeypatch):
    page: dict[str, object] = {"events": [{"ts": "t1", "type": "chat", "text": "only"}], "cursor": None}
    monkeypatch.setattr(commands, "_api_get", _make_api_get([page], []))

    result = commands._recent_messages("http://x", 20)

    assert result == [{"timestamp": "t1", "role": "chat", "content": "only"}]


def test_recent_messages_propagates_error(monkeypatch):
    page: dict[str, object] = {"error": "boom"}
    monkeypatch.setattr(commands, "_api_get", _make_api_get([page], []))

    result = commands._recent_messages("http://x", 5)

    assert result == {"error": "boom"}
