"""Unit tests for microsoft_cli.email.reply_draft (mocked Graph calls)."""

from types import SimpleNamespace

import pytest
from microsoft_cli import backend, cli, email
from microsoft_cli.config import Config

QUOTED = "<div>quoted original</div>"


@pytest.fixture
def patched(monkeypatch):
    calls: list[dict] = []

    def fake_account_id(account_email, cache_file):
        return "acct-1"

    def fake_request(conn, method, path, account_id=None, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs["json"] if "json" in kwargs else None})
        if method == "POST" and path.endswith("/createReply"):
            return {"id": "reply-draft"}
        if method == "POST" and path.endswith("/createReplyAll"):
            return {"id": "replyall-draft"}
        if method == "GET" and "$select" in (kwargs["params"] if "params" in kwargs else {}) and "body" in kwargs["params"]["$select"]:
            return {
                "body": {"contentType": "HTML", "content": QUOTED},
                "toRecipients": [{"emailAddress": {"address": "sender@x.com"}}],
                "ccRecipients": [{"emailAddress": {"address": "cc@x.com"}}],
            }
        if method == "GET":
            return {"subject": "Re: hi", "isDraft": True, "attachments": []}
        return None

    monkeypatch.setattr(email.auth, "get_account_id_by_email", fake_account_id)
    monkeypatch.setattr(email.graph, "request", fake_request)
    return calls


def test_reply_draft_threads_body_above_quote_and_never_sends(patched):
    result = email.reply_draft(Config(), None, account_email="me@example.com", email_id="orig-1", body="thanks\n- one")

    assert result["status"] == "drafted"
    assert result["id"] == "reply-draft"
    assert result["isDraft"] is True
    assert result["to"] == "sender@x.com"
    assert result["cc"] == "cc@x.com"

    assert patched[0]["path"] == "/me/messages/orig-1/createReply"
    patch_call = next(c for c in patched if c["method"] == "PATCH")
    content = patch_call["json"]["body"]["content"]
    assert content.endswith("<br><br>" + QUOTED)
    assert content.index("thanks") < content.index(QUOTED)
    assert "<li>one</li>" in content
    assert not any(c["path"].endswith("/send") for c in patched)


def test_reply_all_uses_create_reply_all(patched):
    result = email.reply_draft(Config(), None, account_email="me@example.com", email_id="orig-1", body="hi", reply_all=True)
    assert result["id"] == "replyall-draft"
    assert patched[0]["path"] == "/me/messages/orig-1/createReplyAll"


def test_replace_draft_deletes_prior_draft_first(patched):
    email.reply_draft(Config(), None, account_email="me@example.com", email_id="orig-1", body="hi", replace_draft="old-9")
    assert patched[0]["method"] == "DELETE"
    assert patched[0]["path"] == "/me/messages/old-9"


def test_reply_draft_escapes_body(patched):
    email.reply_draft(Config(), None, account_email="me@example.com", email_id="orig-1", body="<script>x</script>")
    patch_call = next(c for c in patched if c["method"] == "PATCH")
    content = patch_call["json"]["body"]["content"]
    assert "&lt;script&gt;" in content
    assert "<script>" not in content


def test_reply_draft_parser_and_dispatch(monkeypatch):
    parser = cli.build_parser()
    args = parser.parse_args(
        ["email", "reply-draft", "--account", "me@example.com", "--id", "m-1", "--body", "hi", "--reply-all", "--replace-draft", "old-1"]
    )
    assert args.command == "reply-draft"
    assert args.reply_all is True
    assert args.replace_draft == "old-1"

    seen = {}
    monkeypatch.setattr(cli.email, "reply_draft", lambda cfg, client, **kw: seen.update(kw) or "drafted")
    dispatch_args = SimpleNamespace(
        command="reply-draft",
        account="me@example.com",
        email_id="m-1",
        body="hi",
        attachments=None,
        reply_all=True,
        replace_draft="old-1",
        backend=backend.OWA_REST,
    )
    # Graph-only: even with --backend owa-rest the reply-draft path runs the Graph function.
    assert cli._dispatch_email(dispatch_args, Config(), client=None) == "drafted"
    assert seen == {
        "account_email": "me@example.com",
        "email_id": "m-1",
        "body": "hi",
        "attachments": None,
        "reply_all": True,
        "replace_draft": "old-1",
    }
