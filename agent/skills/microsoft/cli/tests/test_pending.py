"""Undo-send window (--hold): enqueue holds, cancel aborts, the daemon dispatch sends after fire-at.

Dispatch is driven with an explicit ``now`` derived from the stored entry's own
fire_at, so no test waits on the wall clock.
"""

import json
from types import SimpleNamespace

import pytest
from microsoft_cli import backend, cli, pending
from microsoft_cli.config import Config
from microsoft_cli.payloads import MailDraft


def _config(tmp_path):
    return Config(data_dir=tmp_path)


def _send_args(**over):
    base = {
        "command": "send",
        "account": "me@example.com",
        "to": ["bob@x.com"],
        "subject": "Hi",
        "body": "body",
        "cc": None,
        "bcc": None,
        "attachments": None,
        "html": False,
        "backend": backend.GRAPH,
        "hold": 30,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _reply_args(**over):
    base = {
        "command": "reply",
        "account": "me@example.com",
        "email_id": "orig-1",
        "body": "thanks",
        "attachments": None,
        "reply_all": True,
        "html": False,
        "backend": backend.GRAPH,
        "hold": 30,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _forward_args(**over):
    base = {
        "command": "forward",
        "account": "me@example.com",
        "email_id": "orig-1",
        "to": ["bob@x.com"],
        "body": "fyi",
        "cc": None,
        "attachments": None,
        "html": False,
        "backend": backend.GRAPH,
        "hold": 30,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _guard_all_sends(monkeypatch):
    """Make every transmit function on BOTH backends explode if it's ever reached."""
    calls = []

    def boom(name):
        def _f(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} must not be called while the send is held")

        return _f

    for mod, prefix in ((cli.email, "graph"), (cli.owa_rest_commands, "rest")):
        for fn in ("send_email", "reply_to_email", "forward_email"):
            monkeypatch.setattr(mod, fn, boom(f"{prefix}.{fn}"))
    return calls


def test_hold_enqueues_without_sending(monkeypatch, tmp_path):
    calls = _guard_all_sends(monkeypatch)
    config = _config(tmp_path)

    result = cli._dispatch_email(_send_args(), config, client=None)

    token = result["held"]["token"]
    assert result["cancel"] == f"microsoft email cancel --token {token}"
    assert (tmp_path / "pending-sends" / f"{token}.json").exists()
    assert calls == []


def test_hold_validates_recipient_up_front(tmp_path):
    with pytest.raises(ValueError, match="recipient"):
        cli._dispatch_email(_send_args(to=None), _config(tmp_path), client=None)


def test_hold_validates_attachments_up_front(tmp_path):
    with pytest.raises(ValueError, match="attachment not found"):
        cli._dispatch_email(_send_args(attachments=[str(tmp_path / "missing.pdf")]), _config(tmp_path), client=None)


def test_hold_rejects_nonpositive_window(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        cli._dispatch_email(_send_args(hold=0), _config(tmp_path), client=None)


def test_draft_only_mode_refuses_a_held_send(monkeypatch, tmp_path):
    monkeypatch.setenv("EMAIL_DRAFT_ONLY", "1")
    with pytest.raises(RuntimeError, match="draft-only"):
        cli._dispatch_email(_send_args(), _config(tmp_path), client=None)


def test_cancel_prevents_dispatch(monkeypatch, tmp_path):
    calls = _guard_all_sends(monkeypatch)
    config = _config(tmp_path)
    token = cli._dispatch_email(_send_args(), config, client=None)["held"]["token"]
    entry = pending.list_pending(config)[0]

    result = cli._dispatch_email(SimpleNamespace(command="cancel", token=token), config, client=None)

    assert result == {"cancelled": token}
    assert pending.dispatch_due(config, None, now=entry.fire_at + 1) == []
    assert pending.list_pending(config) == []
    assert calls == []


def test_cancel_unknown_token_errors(tmp_path):
    with pytest.raises(ValueError, match="no held send"):
        cli._dispatch_email(SimpleNamespace(command="cancel", token="deadbeef"), _config(tmp_path), client=None)


@pytest.mark.parametrize(
    ("args", "target", "expected_kw"),
    [
        (
            _send_args(),
            "send_email",
            {
                "account_email": "me@example.com",
                "mail": MailDraft(to=["bob@x.com"], subject="Hi", body="body"),
            },
        ),
        (
            _reply_args(),
            "reply_to_email",
            {
                "account_email": "me@example.com",
                "email_id": "orig-1",
                "body": "thanks",
                "attachments": None,
                "reply_all": True,
                "html": False,
            },
        ),
        (
            _forward_args(),
            "forward_email",
            {
                "account_email": "me@example.com",
                "email_id": "orig-1",
                "mail": MailDraft(to=["bob@x.com"], body="fyi"),
            },
        ),
    ],
    ids=["send", "reply", "forward"],
)
def test_dispatch_after_fire_at_sends_via_the_stored_backend(monkeypatch, tmp_path, args, target, expected_kw):
    config = _config(tmp_path)
    cli._dispatch_email(args, config, client=None)
    entry = pending.list_pending(config)[0]
    seen = {}
    monkeypatch.setattr(pending.email, target, lambda cfg, client, **kw: seen.update(kw) or {"status": "sent"})

    outcomes = pending.dispatch_due(config, "fake-client", now=entry.fire_at + 1)

    assert [(e.token, err) for e, err in outcomes] == [(entry.token, None)]
    assert seen == expected_kw
    assert pending.list_pending(config) == []


def test_dispatch_before_fire_at_leaves_the_entry_queued(monkeypatch, tmp_path):
    calls = _guard_all_sends(monkeypatch)
    config = _config(tmp_path)
    token = cli._dispatch_email(_send_args(), config, client=None)["held"]["token"]
    entry = pending.list_pending(config)[0]

    assert pending.dispatch_due(config, None, now=entry.fire_at - 1) == []
    assert [e.token for e in pending.list_pending(config)] == [token]
    assert calls == []


def test_list_pending_shows_entries_in_fire_order(monkeypatch, tmp_path):
    _guard_all_sends(monkeypatch)
    config = _config(tmp_path)
    later = cli._dispatch_email(_send_args(hold=120, subject="Later"), config, client=None)["held"]["token"]
    sooner = cli._dispatch_email(_send_args(hold=30, subject="Sooner"), config, client=None)["held"]["token"]

    rows = cli._dispatch_email(SimpleNamespace(command="list-pending"), config, client=None)

    assert [(r["token"], r["subject"], r["command"]) for r in rows] == [(sooner, "Sooner", "send"), (later, "Later", "send")]
    assert 0 < rows[0]["fires_in_seconds"] <= 30
    assert 0 < rows[1]["fires_in_seconds"] <= 120


def test_failed_dispatch_parks_the_entry_and_reports_the_error(monkeypatch, tmp_path):
    config = _config(tmp_path)
    cli._dispatch_email(_send_args(), config, client=None)
    entry = pending.list_pending(config)[0]

    def explode(cfg, client, **kw):
        raise RuntimeError("graph is down")

    monkeypatch.setattr(pending.email, "send_email", explode)

    outcomes = pending.dispatch_due(config, "fake-client", now=entry.fire_at + 1)

    assert [(e.token, err) for e, err in outcomes] == [(entry.token, "graph is down")]
    assert pending.list_pending(config) == []
    failed = tmp_path / "pending-sends" / f"{entry.token}.failed"
    assert json.loads(failed.read_text())["error"] == "graph is down"
