"""Unit tests for microsoft_cli.email.create_email_draft (mocked Graph calls)."""

import pytest
from microsoft_cli import email
from microsoft_cli.config import Config
from microsoft_cli.payloads import MailDraft


@pytest.fixture
def patched(monkeypatch):
    calls: list[dict] = []

    def fake_account_id(account_email, cache_file):
        return "acct-1"

    def fake_request(conn, method, path, account_id=None, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs["json"] if "json" in kwargs else None})
        if method == "POST" and path.endswith("/createReply"):
            return {"id": "reply-draft"}
        if method == "POST" and path.endswith("/createForward"):
            return {"id": "fwd-draft"}
        if method == "POST" and path == "/me/messages":
            return {"id": "compose-draft"}
        return None

    monkeypatch.setattr(email.auth, "get_account_id_by_email", fake_account_id)
    monkeypatch.setattr(email.graph, "request", fake_request)
    return calls


def test_compose_draft(patched):
    result = email.create_email_draft(
        Config(), None, account_email="me@example.com", mail=MailDraft(subject="Hi", body="body", to=["bob@x.com"])
    )
    assert result["id"] == "compose-draft"
    assert patched[0]["path"] == "/me/messages"
    assert patched[0]["json"]["subject"] == "Hi"


def test_compose_requires_subject(patched):
    with pytest.raises(ValueError, match="--subject is required"):
        email.create_email_draft(Config(), None, account_email="me@example.com", mail=MailDraft(body="body", to=["bob@x.com"]))


def test_compose_requires_recipient(patched):
    with pytest.raises(ValueError, match="At least one recipient"):
        email.create_email_draft(Config(), None, account_email="me@example.com", mail=MailDraft(subject="Hi", body="body"))


def test_reply_draft_is_threaded_and_not_sent(patched):
    result = email.create_email_draft(Config(), None, account_email="me@example.com", mail=MailDraft(body="thanks", reply_to_id="orig-1"))
    assert result == {"status": "drafted", "id": "reply-draft", "source_id": "orig-1"}
    assert patched[0]["path"] == "/me/messages/orig-1/createReply"
    assert patched[1]["method"] == "PATCH"
    assert patched[1]["path"] == "/me/messages/reply-draft"
    assert patched[1]["json"]["body"] == {"contentType": "Text", "content": "thanks"}
    assert not any(c["path"].endswith("/send") for c in patched)


def test_forward_draft_with_recipient(patched):
    result = email.create_email_draft(
        Config(), None, account_email="me@example.com", mail=MailDraft(body="fyi", forward_id="orig-2", to=["bob@x.com"])
    )
    assert result["id"] == "fwd-draft"
    assert patched[0]["path"] == "/me/messages/orig-2/createForward"
    assert patched[1]["json"]["toRecipients"] == [{"emailAddress": {"address": "bob@x.com"}}]


def test_reply_and_forward_mutually_exclusive(patched):
    with pytest.raises(ValueError, match="at most one"):
        email.create_email_draft(Config(), None, account_email="me@example.com", mail=MailDraft(body="x", reply_to_id="a", forward_id="b"))
