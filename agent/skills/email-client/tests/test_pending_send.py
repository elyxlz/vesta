import json
from datetime import UTC, datetime, timedelta

import pending_send
import pytest
import smtp_send


def test_delay_defaults_to_thirty_seconds_and_persists(tmp_path):
    assert pending_send.delay_seconds(tmp_path) == 30

    pending_send.set_delay_seconds(tmp_path, 75)

    assert pending_send.delay_seconds(tmp_path) == 75


def test_pending_send_uses_the_client_delay_and_can_be_claimed_once(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    queued = pending_send.enqueue(
        tmp_path,
        account="personal",
        action="reply",
        subject="Re: Hello",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"mime",
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
        account="personal",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"mime",
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
        account="personal",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"mime",
        now=now,
    )

    assert [item.id for item in pending_send.list_pending(tmp_path)] == [queued.id]

    pending_send.cancel(tmp_path, queued.id)

    assert pending_send.claim_due(tmp_path, now=queued.send_at) is None


def test_a_send_being_dispatched_can_no_longer_be_undone(tmp_path):
    queued = pending_send.enqueue(
        tmp_path,
        account="personal",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"mime",
    )
    pending_send.claim_due(tmp_path, now=queued.send_at)

    with pytest.raises(ValueError, match="being delivered"):
        pending_send.cancel(tmp_path, queued.id)


def test_changing_delay_only_affects_new_sends(tmp_path):
    now = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)
    first = pending_send.enqueue(
        tmp_path,
        account="personal",
        action="send",
        subject="First",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"first",
        now=now,
    )
    pending_send.set_delay_seconds(tmp_path, 75)
    second = pending_send.enqueue(
        tmp_path,
        account="personal",
        action="send",
        subject="Second",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"second",
        now=now,
    )

    assert first.send_at == now + timedelta(seconds=30)
    assert second.send_at == now + timedelta(seconds=75)


def test_a_send_interrupted_mid_dispatch_is_held_instead_of_resent(tmp_path):
    queued = pending_send.enqueue(
        tmp_path,
        account="personal",
        action="forward",
        subject="Fwd: Hello",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"mime",
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
        account="personal",
        action="send",
        subject="Hello",
        recipients="bob@example.com",
        backend="smtp",
        payload=b"mime",
    )
    at = queued.send_at

    for _ in range(pending_send.MAX_DELIVERY_ATTEMPTS):
        at = at + timedelta(seconds=pending_send.RETRY_DELAY_SECONDS)
        assert pending_send.claim_due(tmp_path, now=at).id == queued.id
        pending_send.retry(tmp_path, queued.id, "smtp refused", now=at)

    assert pending_send.claim_due(tmp_path, now=at + timedelta(hours=1)) is None
    assert pending_send.list_pending(tmp_path)[0].public()["last_error"] == "smtp refused"


def _smtp_profile():
    return "generic", {
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_starttls": True,
        "auth_strategy": "app-password",
        "sent_folder": "Sent",
    }


def _patch_account(monkeypatch):
    monkeypatch.setattr(smtp_send, "resolve_account", lambda _account: "personal")
    monkeypatch.setattr(smtp_send, "account_user", lambda _account: "me@example.com")
    monkeypatch.setattr(smtp_send, "account_profile", lambda _account: _smtp_profile())


def _patch_daemon(monkeypatch, *, running):
    monkeypatch.setattr(smtp_send.daemon_lifecycle, "daemon_running", lambda _state_dir: (running, 4242 if running else None))


def _original_message():
    return {
        "message_id": "<original@example.com>",
        "references": "",
        "subject": "Hello",
        "from": "Alice <alice@example.com>",
        "to": "me@example.com",
        "cc": "team@example.com",
        "date": "Tue, 28 Jul 2026 12:00:00 +0000",
        "body": "Original body",
    }


def test_smtp_send_queues_the_composed_message_and_attachments(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    _patch_account(monkeypatch)
    _patch_daemon(monkeypatch, running=True)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")
    delivered = []
    monkeypatch.setattr(smtp_send, "_smtp_deliver", lambda *_args: delivered.append(True))

    smtp_send.send(
        smtp_send.SendRequest(
            to="bob@example.com",
            subject="Hello",
            body="Body",
            account="personal",
            attach=[str(attachment)],
        )
    )

    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "pending"
    assert delivered == []
    queued = pending_send.list_pending(tmp_path)
    assert len(queued) == 1
    _metadata, message = smtp_send._decode_pending_payload(queued[0].payload)
    assert message["Subject"] == "Hello"
    assert next(message.iter_attachments()).get_filename() == "report.pdf"


def test_smtp_all_outbound_actions_inherit_the_client_delay(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    _patch_account(monkeypatch)
    _patch_daemon(monkeypatch, running=True)
    monkeypatch.setattr(smtp_send, "fetch_original", lambda *_args: _original_message())
    pending_send.set_delay_seconds(tmp_path, 45)
    attachment = tmp_path / "report.pdf"
    attachment.write_bytes(b"pdf")

    smtp_send.send(smtp_send.SendRequest(to="bob@example.com", subject="Hello", body="Body", account="personal"))
    smtp_send.send(
        smtp_send.SendRequest(
            reply_to_uid="10",
            to=None,
            subject=None,
            body="Reply",
            account="personal",
            attach=[str(attachment)],
        )
    )
    smtp_send.send(
        smtp_send.SendRequest(
            to="bob@example.com",
            subject=None,
            forward_uid="11",
            body="Forward",
            account="personal",
            attach=[str(attachment)],
        )
    )
    capsys.readouterr()

    queued = pending_send.list_pending(tmp_path)
    assert [item.action for item in queued] == ["send", "reply", "forward"]
    assert all(item.send_at - item.created_at == timedelta(seconds=45) for item in queued)
    _metadata, reply_message = smtp_send._decode_pending_payload(queued[1].payload)
    assert reply_message["Cc"] == "team@example.com"
    assert next(reply_message.iter_attachments()).get_filename() == "report.pdf"


def test_smtp_zero_client_delay_sends_immediately(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    _patch_account(monkeypatch)
    _patch_daemon(monkeypatch, running=True)
    pending_send.set_delay_seconds(tmp_path, 0)
    delivered = []
    monkeypatch.setattr(smtp_send, "_smtp_deliver", lambda *_args: delivered.append(True))
    monkeypatch.setattr(smtp_send, "_sync_sent", lambda *_args: None)

    smtp_send.send(smtp_send.SendRequest(to="bob@example.com", subject="Hello", body="Body", account="personal"))

    assert delivered == [True]
    assert pending_send.list_pending(tmp_path) == []


def test_smtp_dispatch_delivers_once_then_runs_sent_side_effects(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    _patch_account(monkeypatch)
    _patch_daemon(monkeypatch, running=True)
    smtp_send.send(smtp_send.SendRequest(to="bob@example.com", subject="Hello", body="Body", account="personal"))
    queued = pending_send.list_pending(tmp_path)[0]
    delivered = []
    synced = []
    monkeypatch.setattr(smtp_send, "_smtp_deliver", lambda *_args: delivered.append(True))
    monkeypatch.setattr(smtp_send, "_sync_sent_message", lambda *_args: synced.append(True))

    assert smtp_send.dispatch_due(tmp_path, now=queued.send_at) is True
    assert smtp_send.dispatch_due(tmp_path, now=queued.send_at) is False
    assert delivered == [True]
    assert synced == [True]


def test_smtp_reply_side_effects_wait_for_delivery(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    _patch_account(monkeypatch)
    _patch_daemon(monkeypatch, running=True)
    monkeypatch.setattr(smtp_send, "fetch_original", lambda *_args: _original_message())
    answered = []
    monkeypatch.setattr(smtp_send, "_mark_answered", lambda *_args: answered.append(True))
    monkeypatch.setattr(smtp_send, "_smtp_deliver", lambda *_args: None)
    monkeypatch.setattr(smtp_send, "_sync_sent_message", lambda *_args: None)

    smtp_send.send(
        smtp_send.SendRequest(
            to=None,
            subject=None,
            reply_to_uid="10",
            body="Reply",
            account="personal",
        )
    )
    queued = pending_send.list_pending(tmp_path)[0]
    assert answered == []

    smtp_send.dispatch_due(tmp_path, now=queued.send_at)

    assert answered == [True]


def test_smtp_dispatch_retries_cli_style_delivery_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    _patch_account(monkeypatch)
    _patch_daemon(monkeypatch, running=True)
    smtp_send.send(smtp_send.SendRequest(to="bob@example.com", subject="Hello", body="Body", account="personal"))
    queued = pending_send.list_pending(tmp_path)[0]

    def fail_delivery(*_args):
        raise SystemExit("smtp auth failed")

    monkeypatch.setattr(smtp_send, "_smtp_deliver", fail_delivery)

    with pytest.raises(RuntimeError, match="smtp auth failed"):
        smtp_send.dispatch_due(tmp_path, now=queued.send_at)
    assert [item.id for item in pending_send.list_pending(tmp_path)] == [queued.id]


def test_delay_is_client_configuration_not_a_send_option(tmp_path):
    parser = smtp_send._build_parser()

    args = parser.parse_args(["--to", "bob@example.com", "--subject", "Hello", "--body", "Body"])

    assert "seconds" not in vars(args)


def test_a_delayed_send_is_refused_when_no_daemon_can_dispatch_it(tmp_path, monkeypatch):
    monkeypatch.setenv("EMAIL_CLIENT_DIR", str(tmp_path))
    _patch_account(monkeypatch)
    _patch_daemon(monkeypatch, running=False)
    monkeypatch.setattr(smtp_send, "_smtp_deliver", lambda *_args: pytest.fail("must not deliver"))

    with pytest.raises(SystemExit, match="daemon start"):
        smtp_send.send(smtp_send.SendRequest(to="bob@example.com", subject="Hello", body="Body", account="personal"))

    assert pending_send.list_pending(tmp_path) == []
