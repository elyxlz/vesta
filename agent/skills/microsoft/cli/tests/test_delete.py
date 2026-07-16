"""Unit tests for microsoft_cli.email.delete_email (mocked Graph calls)."""

import pytest
from microsoft_cli import email
from microsoft_cli.config import Config


@pytest.fixture
def patched(monkeypatch):
    calls: list[dict] = []

    def fake_account_id(account_email, cache_file):
        return "acct-123"

    def fake_request(conn, method, path, account_id=None, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs["json"] if "json" in kwargs else None})
        if method == "GET":
            return {"value": calls_state["messages"]}
        return None

    calls_state = {"messages": []}

    monkeypatch.setattr(email.auth, "get_account_id_by_email", fake_account_id)
    monkeypatch.setattr(email.graph, "request", fake_request)
    return calls, calls_state


def test_delete_by_id_soft(patched):
    calls, _ = patched
    result = email.delete_email(Config(), None, account_email="me@example.com", email_id="msg-1")
    assert result == {"status": "deleted", "mode": "soft", "email_id": "msg-1"}
    assert len(calls) == 1
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/me/messages/msg-1/move"
    assert calls[0]["json"] == {"destinationId": "deleteditems"}


def test_delete_by_id_permanent(patched):
    calls, _ = patched
    result = email.delete_email(Config(), None, account_email="me@example.com", email_id="msg-1", permanent=True)
    assert result == {"status": "deleted", "mode": "permanent", "email_id": "msg-1"}
    assert len(calls) == 1
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["path"] == "/me/messages/msg-1"
    assert calls[0]["json"] is None


def test_delete_by_sender_multiple(patched):
    calls, calls_state = patched
    calls_state["messages"] = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    result = email.delete_email(Config(), None, account_email="me@example.com", sender="spam@bad.com")
    assert result["status"] == "deleted"
    assert result["mode"] == "soft"
    assert result["sender"] == "spam@bad.com"
    assert result["deleted_count"] == 3
    assert result["deleted_ids"] == ["a", "b", "c"]

    get_calls = [c for c in calls if c["method"] == "GET"]
    move_calls = [c for c in calls if c["path"].endswith("/move")]
    assert len(get_calls) == 1
    assert len(move_calls) == 3
    assert {c["path"] for c in move_calls} == {"/me/messages/a/move", "/me/messages/b/move", "/me/messages/c/move"}


def test_delete_requires_exactly_one_arg(patched):
    with pytest.raises(ValueError, match="exactly one of --id or --sender"):
        email.delete_email(Config(), None, account_email="me@example.com")
    with pytest.raises(ValueError, match="exactly one of --id or --sender"):
        email.delete_email(Config(), None, account_email="me@example.com", email_id="x", sender="y@z.com")
