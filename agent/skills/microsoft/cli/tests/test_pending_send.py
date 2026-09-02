from datetime import UTC, datetime, timedelta

import pytest
from microsoft_cli import backend, cli, email, owa_rest_commands, pending_send
from microsoft_cli.config import Config
from microsoft_cli.payloads import MailDraft

QUOTED = "<div>quoted original</div>"


def test_delay_defaults_to_thirty_seconds_and_persists(tmp_path):
    assert pending_send.delay_seconds(tmp_path) == 30

    pending_send.set_delay_seconds(tmp_path, 120)

    assert pending_send.delay_seconds(tmp_path) == 120


def test_pending_send_uses_the_client_delay_and_can_be_claimed_once(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="forward",
        subject="Fwd: Hello",
        recipients="bob@example.com",
        backend="graph",
        payload=b"draft-1",
        now=now,
    )

    assert queued.send_at == now + timedelta(seconds=30)
    assert [item.id for item in pending_send.list_pending(tmp_path)] == [queued.id]
    assert pending_send.claim_due(tmp_path, now=queued.send_at - timedelta(microseconds=1)) is None
    assert pending_send.claim_due(tmp_path, now=queued.send_at).id == queued.id
    assert pending_send.claim_due(tmp_path, now=queued.send_at) is None


def test_undo_removes_a_pending_send_before_delivery(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="owa-rest",
        payload=b"draft-1",
        now=now,
    )

    cancelled = pending_send.cancel(tmp_path, queued.id)

    assert cancelled.id == queued.id
    assert pending_send.list_pending(tmp_path) == []
    assert pending_send.claim_due(tmp_path, now=queued.send_at) is None


def test_undo_rejects_an_unknown_send(tmp_path):
    with pytest.raises(ValueError, match="was not found"):
        pending_send.cancel(tmp_path, "nope")


def test_an_overdue_send_stays_listed_and_undoable_until_it_is_dispatched(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend=pending_send.GRAPH_BACKEND,
        payload=b"draft-1",
        now=now,
    )

    assert [item.id for item in pending_send.list_pending(tmp_path)] == [queued.id]

    pending_send.cancel(tmp_path, queued.id)

    assert pending_send.claim_due(tmp_path, now=queued.send_at) is None


def test_a_send_being_dispatched_can_no_longer_be_undone(tmp_path):
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend=pending_send.GRAPH_BACKEND,
        payload=b"draft-1",
    )
    pending_send.claim_due(tmp_path, now=queued.send_at)

    with pytest.raises(ValueError, match="being delivered"):
        pending_send.cancel(tmp_path, queued.id)


def test_changing_delay_only_affects_new_sends(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    first = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="First",
        recipients="bob@example.com",
        backend="graph",
        payload=b"first",
        now=now,
    )
    pending_send.set_delay_seconds(tmp_path, 120)
    second = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Second",
        recipients="bob@example.com",
        backend="graph",
        payload=b"second",
        now=now,
    )

    assert first.send_at == now + timedelta(seconds=30)
    assert second.send_at == now + timedelta(seconds=120)


def test_a_send_interrupted_mid_dispatch_is_held_instead_of_resent(tmp_path):
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="reply",
        subject="Re: Hello",
        recipients="bob@example.com",
        backend=pending_send.GRAPH_BACKEND,
        payload=b"draft-1",
    )
    assert pending_send.claim_due(tmp_path, now=queued.send_at).id == queued.id

    pending_send.recover_dispatching(tmp_path)

    assert pending_send.claim_due(tmp_path, now=queued.send_at) is None
    held = pending_send.list_pending(tmp_path)[0]
    assert held.public()["status"] == "failed"
    assert held.public()["last_error"] == pending_send.INTERRUPTED_ERROR


def test_delivery_stops_retrying_once_it_has_burned_its_attempts(tmp_path):
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend=pending_send.GRAPH_BACKEND,
        payload=b"draft-1",
    )
    at = queued.send_at

    for _ in range(pending_send.MAX_DELIVERY_ATTEMPTS):
        at = at + timedelta(seconds=pending_send.RETRY_DELAY_SECONDS)
        assert pending_send.claim_due(tmp_path, now=at).id == queued.id
        pending_send.retry(tmp_path, queued.id, "provider refused", now=at)

    assert pending_send.claim_due(tmp_path, now=at + timedelta(hours=1)) is None
    assert pending_send.list_pending(tmp_path)[0].public()["last_error"] == "provider refused"


def _patch_graph(monkeypatch, calls):
    monkeypatch.setattr(email.auth, "get_account_id_by_email", lambda *_args: "account-1")

    def request(_config, _client, method, path, _account_id, **kwargs):
        calls.append({"method": method, "path": path, "json": kwargs["json"] if "json" in kwargs else None})
        if method == "POST" and path.endswith("/createReplyAll"):
            return {"id": "reply-all-draft"}
        if method == "POST" and path.endswith("/createReply"):
            return {"id": "reply-draft"}
        if method == "POST" and path.endswith("/createForward"):
            return {"id": "forward-draft"}
        if method == "POST" and path == "/me/messages":
            return {"id": "compose-draft"}
        if method == "GET":
            return {"body": {"contentType": "HTML", "content": QUOTED}}
        return None

    monkeypatch.setattr(email.graph, "request_cfg", request)


def test_graph_send_creates_a_provider_draft_and_returns_pending(tmp_path, monkeypatch):
    calls = []
    config = Config(data_dir=tmp_path)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    _patch_graph(monkeypatch, calls)

    result = email.send_email(
        config,
        None,
        account_email="me@example.com",
        mail=MailDraft(to=["bob@example.com"], subject="Hello", body="Body", attachments=[str(attachment)]),
    )

    assert result["status"] == "pending"
    assert [call["path"] for call in calls] == ["/me/messages"]
    assert pending_send.list_pending(tmp_path)[0].payload == b"compose-draft"


def test_all_graph_outbound_actions_inherit_the_client_delay(tmp_path, monkeypatch):
    calls = []
    config = Config(data_dir=tmp_path)
    pending_send.set_delay_seconds(tmp_path, 45)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    _patch_graph(monkeypatch, calls)

    email.send_email(
        config,
        None,
        account_email="me@example.com",
        mail=MailDraft(to=["bob@example.com"], subject="Hello", body="Body"),
    )
    email.reply_to_email(
        config,
        None,
        account_email="me@example.com",
        email_id="original-1",
        body="Reply",
        attachments=[str(attachment)],
    )
    email.reply_to_email(
        config,
        None,
        account_email="me@example.com",
        email_id="original-2",
        body="Reply all",
        attachments=[str(attachment)],
        reply_all=True,
    )
    email.forward_email(
        config,
        None,
        account_email="me@example.com",
        email_id="original-3",
        mail=MailDraft(to=["bob@example.com"], body="Forward", attachments=[str(attachment)]),
    )

    queued = pending_send.list_pending(tmp_path)
    assert [item.action for item in queued] == ["send", "reply", "reply-all", "forward"]
    assert all(item.send_at - item.created_at == timedelta(seconds=45) for item in queued)


def test_graph_zero_client_delay_sends_immediately(tmp_path, monkeypatch):
    calls = []
    config = Config(data_dir=tmp_path)
    pending_send.set_delay_seconds(tmp_path, 0)
    _patch_graph(monkeypatch, calls)

    result = email.send_email(
        config,
        None,
        account_email="me@example.com",
        mail=MailDraft(to=["bob@example.com"], subject="Hello", body="Body"),
    )

    assert result == {"status": "sent"}
    assert [call["path"] for call in calls] == ["/me/sendMail"]
    assert pending_send.list_pending(tmp_path) == []


def test_graph_reply_all_creates_a_threaded_draft(tmp_path, monkeypatch):
    calls = []
    config = Config(data_dir=tmp_path)
    _patch_graph(monkeypatch, calls)

    result = email.reply_to_email(
        config,
        None,
        account_email="me@example.com",
        email_id="original-1",
        body="Thanks",
        reply_all=True,
    )

    assert result["status"] == "pending"
    assert [(call["method"], call["path"]) for call in calls] == [
        ("POST", "/me/messages/original-1/createReplyAll"),
        ("GET", "/me/messages/reply-all-draft"),
        ("PATCH", "/me/messages/reply-all-draft"),
    ]
    assert calls[2]["json"]["body"]["content"].endswith("<br><br>" + QUOTED)
    assert pending_send.list_pending(tmp_path)[0].action == "reply-all"


def test_graph_immediate_reply_with_attachments_sends_the_body_over_the_quote(tmp_path, monkeypatch):
    calls = []
    config = Config(data_dir=tmp_path)
    pending_send.set_delay_seconds(tmp_path, 0)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    _patch_graph(monkeypatch, calls)

    result = email.reply_to_email(
        config, None, account_email="me@example.com", email_id="original-1", body="Thanks", attachments=[str(attachment)]
    )

    assert result == {"status": "sent"}
    assert [(call["method"], call["path"]) for call in calls] == [
        ("POST", "/me/messages/original-1/createReply"),
        ("GET", "/me/messages/reply-draft"),
        ("PATCH", "/me/messages/reply-draft"),
        ("POST", "/me/messages/reply-draft/attachments"),
        ("POST", "/me/messages/reply-draft/send"),
    ]
    content = calls[2]["json"]["body"]["content"]
    assert content.index("Thanks") < content.index(QUOTED)
    assert content.endswith("<br><br>" + QUOTED)


def test_graph_large_attachment_is_uploaded_before_the_draft_is_queued(tmp_path, monkeypatch):
    calls = []
    uploads = []
    config = Config(data_dir=tmp_path)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    _patch_graph(monkeypatch, calls)
    monkeypatch.setattr(email, "LARGE_ATTACHMENT_THRESHOLD", 1)
    monkeypatch.setattr(email.graph, "upload_mail_attachment_cfg", lambda *_args: uploads.append(_args))

    result = email.send_email(
        config,
        None,
        account_email="me@example.com",
        mail=MailDraft(to=["bob@example.com"], subject="Hello", body="Body", attachments=[str(attachment)]),
    )

    assert result["status"] == "pending"
    assert len(uploads) == 1
    assert pending_send.list_pending(tmp_path)[0].payload == b"compose-draft"


def test_owa_send_creates_a_provider_draft_and_returns_pending(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    calls = []

    def create_draft(_client, account_email, _config, *, mail):
        calls.append((account_email, mail))
        return {"id": "owa-draft"}

    monkeypatch.setattr(owa_rest_commands.owa_rest, "create_draft", create_draft)

    result = owa_rest_commands.send_email(
        config,
        None,
        account_email="me@example.com",
        mail=MailDraft(to=["bob@example.com"], subject="Hello", body="Body"),
    )

    assert result["status"] == "pending"
    assert len(calls) == 1
    queued = pending_send.list_pending(tmp_path)[0]
    assert queued.backend == backend.OWA_REST
    assert queued.payload == b"owa-draft"


def test_all_owa_outbound_actions_and_attachments_use_provider_drafts(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    pending_send.set_delay_seconds(tmp_path, 70)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    drafts = []

    def create_draft(_client, account_email, _config, *, mail):
        drafts.append((account_email, mail))
        if mail.reply_to_id:
            draft_id = "reply-all-draft" if mail.reply_all else "reply-draft"
        elif mail.forward_id:
            draft_id = "forward-draft"
        else:
            draft_id = "send-draft"
        return {"id": draft_id}

    monkeypatch.setattr(owa_rest_commands.owa_rest, "create_draft", create_draft)

    owa_rest_commands.send_email(
        config,
        None,
        account_email="me@example.com",
        mail=MailDraft(
            to=["bob@example.com"],
            subject="Hello",
            body="Body",
            attachments=[str(attachment)],
        ),
    )
    owa_rest_commands.reply_to_email(
        config,
        None,
        account_email="me@example.com",
        email_id="original-1",
        body="Reply",
        attachments=[str(attachment)],
    )
    owa_rest_commands.reply_to_email(
        config,
        None,
        account_email="me@example.com",
        email_id="original-2",
        body="Reply all",
        reply_all=True,
    )
    owa_rest_commands.forward_email(
        config,
        None,
        account_email="me@example.com",
        email_id="original-3",
        mail=MailDraft(to=["bob@example.com"], body="Forward", attachments=[str(attachment)]),
    )

    queued = pending_send.list_pending(tmp_path)
    assert [item.action for item in queued] == ["send", "reply", "reply-all", "forward"]
    assert all(item.send_at - item.created_at == timedelta(seconds=70) for item in queued)
    assert drafts[0][1].attachments == [str(attachment)]
    assert drafts[1][1].attachments == [str(attachment)]
    assert drafts[3][1].attachments == [str(attachment)]


def test_dispatch_sends_the_graph_draft_once(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    calls = []
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend=backend.GRAPH,
        payload=b"draft-1",
    )
    monkeypatch.setattr(pending_send.auth, "get_account_id_by_email", lambda *_args: "account-1")
    monkeypatch.setattr(
        pending_send.graph,
        "request_cfg",
        lambda _config, _client, method, path, _account_id: calls.append((method, path)),
    )

    assert pending_send.dispatch_due(config, None, now=queued.send_at) is True
    assert pending_send.dispatch_due(config, None, now=queued.send_at) is False
    assert calls == [("POST", "/me/messages/draft-1/send")]


def test_dispatch_sends_the_owa_draft_once(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    calls = []
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend=backend.OWA_REST,
        payload=b"draft-1",
    )
    monkeypatch.setattr(
        pending_send.owa_rest,
        "send_draft",
        lambda _client, account, _config, *, item_id: calls.append((account, item_id)),
    )

    assert pending_send.dispatch_due(config, None, now=queued.send_at) is True
    assert pending_send.dispatch_due(config, None, now=queued.send_at) is False
    assert calls == [("me@example.com", "draft-1")]


def test_undo_deletes_the_provider_draft(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    calls = []
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend=backend.GRAPH,
        payload=b"draft-1",
    )
    monkeypatch.setattr(pending_send.auth, "get_account_id_by_email", lambda *_args: "account-1")
    monkeypatch.setattr(
        pending_send.graph,
        "request_cfg",
        lambda _config, _client, method, path, _account_id: calls.append((method, path)),
    )

    result = pending_send.undo(config, None, queued.id)

    assert result == {"id": queued.id, "status": "cancelled"}
    assert calls == [("DELETE", "/me/messages/draft-1")]
    assert pending_send.list_pending(tmp_path) == []


def test_undo_deletes_the_owa_provider_draft(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    calls = []
    queued = pending_send.enqueue(
        tmp_path,
        account="me@example.com",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend=backend.OWA_REST,
        payload=b"draft-1",
    )
    monkeypatch.setattr(
        pending_send.owa_rest,
        "delete_message",
        lambda _client, account, _config, *, item_id: calls.append((account, item_id)),
    )

    result = pending_send.undo(config, None, queued.id)

    assert result == {"id": queued.id, "status": "cancelled"}
    assert calls == [("me@example.com", "draft-1")]
    assert pending_send.list_pending(tmp_path) == []


def test_delay_is_client_configuration_not_a_send_option(tmp_path):
    parser = cli.build_parser()
    send_args = parser.parse_args(
        ["email", "send", "--account", "me@example.com", "--to", "bob@example.com", "--subject", "Hello", "--body", "Body"]
    )
    delay_args = parser.parse_args(["email", "send-delay", "--seconds", "45"])

    assert "seconds" not in vars(send_args)
    assert cli._dispatch_email(delay_args, Config(data_dir=tmp_path), None) == {"send_delay_seconds": 45}
