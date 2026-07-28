from datetime import UTC, datetime, timedelta

import pytest
from google_cli import cli, gmail, pending_send
from google_cli.config import Config


def test_delay_defaults_to_thirty_seconds_and_persists(tmp_path):
    assert pending_send.delay_seconds(tmp_path) == 30

    pending_send.set_delay_seconds(tmp_path, 90)

    assert pending_send.delay_seconds(tmp_path) == 90


def test_pending_send_uses_the_client_delay_and_can_be_claimed_once(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    queued = pending_send.enqueue(
        tmp_path,
        account="google",
        action="reply-all",
        subject="Re: Hello",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"draft-1",
        now=now,
    )

    assert queued.send_at == now + timedelta(seconds=30)
    assert [item.id for item in pending_send.list_pending(tmp_path, now=now)] == [queued.id]
    assert pending_send.claim_due(tmp_path, now=queued.send_at - timedelta(microseconds=1)) is None
    assert pending_send.claim_due(tmp_path, now=queued.send_at).id == queued.id
    assert pending_send.claim_due(tmp_path, now=queued.send_at) is None


def test_undo_removes_a_pending_send_before_delivery(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    queued = pending_send.enqueue(
        tmp_path,
        account="google",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"draft-1",
        now=now,
    )

    cancelled = pending_send.cancel(tmp_path, queued.id, now=queued.send_at - timedelta(microseconds=1))

    assert cancelled.id == queued.id
    assert pending_send.list_pending(tmp_path) == []
    assert pending_send.claim_due(tmp_path, now=queued.send_at) is None


def test_undo_rejects_a_send_after_its_recovery_window(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    queued = pending_send.enqueue(
        tmp_path,
        account="google",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"draft-1",
        now=now,
    )

    with pytest.raises(ValueError, match="expired"):
        pending_send.cancel(tmp_path, queued.id, now=queued.send_at)
    assert pending_send.list_pending(tmp_path, now=queued.send_at) == []


def test_changing_delay_only_affects_new_sends(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    first = pending_send.enqueue(
        tmp_path,
        account="google",
        action="send",
        subject="First",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"first",
        now=now,
    )
    pending_send.set_delay_seconds(tmp_path, 90)
    second = pending_send.enqueue(
        tmp_path,
        account="google",
        action="send",
        subject="Second",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"second",
        now=now,
    )

    assert first.send_at == now + timedelta(seconds=30)
    assert second.send_at == now + timedelta(seconds=90)


def test_dispatching_send_recovers_after_daemon_restart(tmp_path):
    queued = pending_send.enqueue(
        tmp_path,
        account="google",
        action="reply",
        subject="Re: Hello",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"draft-1",
    )
    assert pending_send.claim_due(tmp_path, now=queued.send_at).id == queued.id

    pending_send.recover_dispatching(tmp_path)

    assert pending_send.claim_due(tmp_path, now=queued.send_at).id == queued.id


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class _Messages:
    def __init__(self, calls):
        self.calls = calls

    def send(self, **kwargs):
        self.calls.append(("message-send", kwargs))
        return _Request({"id": "sent-1"})

    def get(self, **kwargs):
        self.calls.append(("message-get", kwargs))
        return _Request(
            {
                "threadId": "thread-1",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hello"},
                        {"name": "From", "value": "alice@example.com"},
                        {"name": "To", "value": "me@example.com"},
                        {"name": "Message-ID", "value": "<original@example.com>"},
                    ]
                },
            }
        )


class _Drafts:
    def __init__(self, calls):
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(("draft-create", kwargs))
        return _Request({"id": "draft-1", "message": {"id": "message-1"}})

    def send(self, **kwargs):
        self.calls.append(("draft-send", kwargs))
        return _Request({"id": "sent-1"})

    def delete(self, **kwargs):
        self.calls.append(("draft-delete", kwargs))
        return _Request({})


class _Users:
    def __init__(self, calls):
        self.messages_api = _Messages(calls)
        self.drafts_api = _Drafts(calls)

    def messages(self):
        return self.messages_api

    def drafts(self):
        return self.drafts_api


class _Gmail:
    def __init__(self):
        self.calls = []
        self.users_api = _Users(self.calls)

    def users(self):
        return self.users_api


def test_send_creates_a_provider_draft_and_returns_pending(tmp_path, monkeypatch):
    service = _Gmail()
    config = Config(data_dir=tmp_path)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    monkeypatch.setattr(gmail.api, "gmail_service", lambda _config: service)

    result = gmail.send_email(config, to=["bob@example.com"], subject="Hello", body="Body", attachments=[str(attachment)])

    assert result["status"] == "pending"
    assert [name for name, _kwargs in service.calls] == ["draft-create"]
    queued = pending_send.list_pending(tmp_path)
    assert len(queued) == 1
    assert queued[0].payload == b"draft-1"


def test_all_google_outbound_actions_inherit_the_client_delay(tmp_path, monkeypatch):
    service = _Gmail()
    config = Config(data_dir=tmp_path)
    pending_send.set_delay_seconds(tmp_path, 45)
    monkeypatch.setattr(gmail.api, "gmail_service", lambda _config: service)

    gmail.send_email(config, to=["bob@example.com"], subject="Hello", body="Body")
    gmail.reply_to_email(config, message_id="original-1", body="Reply")
    gmail.reply_to_email(config, message_id="original-2", body="Reply all", reply_all=True)

    queued = pending_send.list_pending(tmp_path)
    assert [item.action for item in queued] == ["send", "reply", "reply-all"]
    assert all(item.send_at - item.created_at == timedelta(seconds=45) for item in queued)


def test_zero_client_delay_sends_immediately(tmp_path, monkeypatch):
    service = _Gmail()
    config = Config(data_dir=tmp_path)
    pending_send.set_delay_seconds(tmp_path, 0)
    monkeypatch.setattr(gmail.api, "gmail_service", lambda _config: service)

    result = gmail.send_email(config, to=["bob@example.com"], subject="Hello", body="Body")

    assert result == {"status": "sent", "id": "sent-1"}
    assert [name for name, _kwargs in service.calls] == ["message-send"]
    assert pending_send.list_pending(tmp_path) == []


def test_reply_all_is_queued_as_a_threaded_provider_draft(tmp_path, monkeypatch):
    service = _Gmail()
    config = Config(data_dir=tmp_path)
    monkeypatch.setattr(gmail.api, "gmail_service", lambda _config: service)

    result = gmail.reply_to_email(config, message_id="original-1", body="Thanks", reply_all=True)

    assert result["status"] == "pending"
    assert [name for name, _kwargs in service.calls] == ["message-get", "draft-create"]
    assert pending_send.list_pending(tmp_path)[0].action == "reply-all"


def test_reply_attachment_is_resolved_before_the_provider_draft_is_queued(tmp_path, monkeypatch):
    service = _Gmail()
    config = Config(data_dir=tmp_path)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    monkeypatch.setattr(gmail.api, "gmail_service", lambda _config: service)

    result = gmail.reply_to_email(
        config,
        message_id="original-1",
        body="Thanks",
        attachments=[str(attachment)],
    )

    assert result["status"] == "pending"
    assert [name for name, _kwargs in service.calls] == ["message-get", "draft-create"]


def test_dispatch_sends_the_provider_draft_once(tmp_path, monkeypatch):
    service = _Gmail()
    config = Config(data_dir=tmp_path)
    monkeypatch.setattr(gmail.api, "gmail_service", lambda _config: service)
    queued = pending_send.enqueue(
        tmp_path,
        account="google",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"draft-1",
    )

    assert gmail.dispatch_due(config, now=queued.send_at) is True
    assert gmail.dispatch_due(config, now=queued.send_at) is False
    assert [name for name, _kwargs in service.calls] == ["draft-send"]


def test_undo_deletes_the_provider_draft(tmp_path, monkeypatch):
    service = _Gmail()
    config = Config(data_dir=tmp_path)
    monkeypatch.setattr(gmail.api, "gmail_service", lambda _config: service)
    queued = pending_send.enqueue(
        tmp_path,
        account="google",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="gmail",
        payload=b"draft-1",
    )

    result = gmail.undo_pending(config, queued.id)

    assert result == {"id": queued.id, "status": "cancelled"}
    assert [name for name, _kwargs in service.calls] == ["draft-delete"]
    assert pending_send.list_pending(tmp_path) == []


def test_delay_is_client_configuration_not_a_send_option(tmp_path):
    parser = cli._build_parser()
    send_args = parser.parse_args(["email", "send", "--to", "bob@example.com", "--subject", "Hello", "--body", "Body"])
    delay_args = parser.parse_args(["email", "send-delay", "--seconds", "45"])

    assert "seconds" not in vars(send_args)
    assert cli._dispatch_email(delay_args, Config(data_dir=tmp_path)) == {"send_delay_seconds": 45}
