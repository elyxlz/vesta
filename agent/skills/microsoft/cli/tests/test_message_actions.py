"""Unit tests for forward / move / archive / flag message actions (mocked Graph)."""

import pytest
from microsoft_cli import email, pending_send
from microsoft_cli.config import Config
from microsoft_cli.payloads import MailDraft

QUOTED = "<div>quoted original</div>"
_FOLDERS_PAGE = {
    "value": [
        {"id": "news-id", "displayName": "Newsletters", "childFolders": []},
    ]
}


@pytest.fixture
def patched(monkeypatch):
    calls: list[dict] = []

    def fake_account_id(account_email, cache_file):
        return "acct-1"

    def fake_request(conn, method, path, account_id=None, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs["json"] if "json" in kwargs else None})
        if method == "GET" and path == "/me/mailFolders":
            return _FOLDERS_PAGE
        if method == "POST" and path.endswith("/createForward"):
            return {"id": "draft-1"}
        if method == "POST" and path.endswith("/move"):
            return {"id": "moved-1"}
        if method == "GET":
            return {"body": {"contentType": "HTML", "content": QUOTED}}
        return None

    monkeypatch.setattr(email.auth, "get_account_id_by_email", fake_account_id)
    monkeypatch.setattr(email.graph, "request", fake_request)
    return calls


def test_forward_plain_uses_forward_action(patched, tmp_path):
    pending_send.set_delay_seconds(tmp_path, 0)
    result = email.forward_email(
        Config(data_dir=tmp_path), None, account_email="me@example.com", email_id="m1", mail=MailDraft(to=["bob@x.com"], body="fyi")
    )
    assert result == {"status": "sent"}
    assert len(patched) == 1
    assert patched[0]["path"] == "/me/messages/m1/forward"
    assert patched[0]["json"] == {"comment": "fyi", "toRecipients": [{"emailAddress": {"address": "bob@x.com"}}]}


def test_forward_with_cc_uses_draft_path(patched, tmp_path):
    pending_send.set_delay_seconds(tmp_path, 0)
    result = email.forward_email(
        Config(data_dir=tmp_path),
        None,
        account_email="me@example.com",
        email_id="m1",
        mail=MailDraft(to=["bob@x.com"], body="fyi", cc=["cc@x.com"]),
    )
    assert result == {"status": "sent"}
    assert [(c["method"], c["path"]) for c in patched] == [
        ("POST", "/me/messages/m1/createForward"),
        ("PATCH", "/me/messages/draft-1"),
        ("GET", "/me/messages/draft-1"),
        ("PATCH", "/me/messages/draft-1"),
        ("POST", "/me/messages/draft-1/send"),
    ]
    recipients = patched[1]["json"]
    assert recipients["ccRecipients"] == [{"emailAddress": {"address": "cc@x.com"}}]
    assert recipients["toRecipients"] == [{"emailAddress": {"address": "bob@x.com"}}]
    content = patched[3]["json"]["body"]["content"]
    assert content.index("fyi") < content.index(QUOTED)
    assert content.endswith("<br><br>" + QUOTED)


def test_forward_requires_to(patched, tmp_path):
    with pytest.raises(ValueError, match="--to is required"):
        email.forward_email(Config(data_dir=tmp_path), None, account_email="me@example.com", email_id="m1", mail=MailDraft(to=[]))


def test_move_to_wellknown_folder(patched):
    result = email.move_email(Config(), None, account_email="me@example.com", email_id="m1", to_folder="Archive")
    assert result == {"status": "moved", "email_id": "m1", "to_folder": "Archive", "new_id": "moved-1"}
    move = next(c for c in patched if c["path"].endswith("/move"))
    assert move["json"] == {"destinationId": "archive"}


def test_move_to_named_folder_resolves_id(patched):
    email.move_email(Config(), None, account_email="me@example.com", email_id="m1", to_folder="Newsletters")
    move = next(c for c in patched if c["path"].endswith("/move"))
    assert move["json"] == {"destinationId": "news-id"}


def test_archive_moves_to_archive(patched):
    result = email.archive_email(Config(), None, account_email="me@example.com", email_id="m1")
    assert result["to_folder"] == "archive"
    move = next(c for c in patched if c["path"].endswith("/move"))
    assert move["json"] == {"destinationId": "archive"}


def test_update_flagged(patched):
    email.update_email(Config(), None, account_email="me@example.com", email_id="m1", flagged=True)
    patch = next(c for c in patched if c["method"] == "PATCH")
    assert patch["path"] == "/me/messages/m1"
    assert patch["json"] == {"flag": {"flagStatus": "flagged"}}


def test_update_unflagged(patched):
    email.update_email(Config(), None, account_email="me@example.com", email_id="m1", flagged=False)
    patch = next(c for c in patched if c["method"] == "PATCH")
    assert patch["json"] == {"flag": {"flagStatus": "notFlagged"}}


def test_update_requires_a_field(patched):
    with pytest.raises(ValueError, match="at least one field"):
        email.update_email(Config(), None, account_email="me@example.com", email_id="m1")
