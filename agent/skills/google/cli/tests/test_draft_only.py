"""EMAIL_DRAFT_ONLY hard send-disable guard in cli._dispatch_email.

The guard sits at the top of _dispatch_email, before any command handling, so
gmail send/reply/forward are refused before any API call. Drafting stays allowed.
"""

from types import SimpleNamespace

import pytest
from google_cli import cli, gmail
from google_cli.config import Config


def _send_args(**over):
    base = {
        "command": "send",
        "to": ["bob@example.com"],
        "subject": "Hi",
        "body": "body",
        "cc": None,
        "attachments": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _reply_args(**over):
    base = {
        "command": "reply",
        "message_id": "orig-1",
        "body": "thanks",
        "attachments": None,
        "reply_all": False,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _draft_args(**over):
    base = {
        "command": "draft",
        "to": ["bob@example.com"],
        "subject": "Hi",
        "body": "body",
        "cc": None,
        "attachments": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _guard_all_sends(monkeypatch):
    """Make every transmit function explode if it is ever reached."""
    calls = []

    def boom(name):
        def _f(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} must not be called in draft-only mode")

        return _f

    monkeypatch.setattr(gmail, "send_email", boom("send_email"))
    monkeypatch.setattr(gmail, "reply_to_email", boom("reply_to_email"))
    return calls


def test_helper_truthy_values(monkeypatch):
    for v in ("1", "true", "TRUE", "Yes", "  yes  "):
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", v)
        assert cli._draft_only_enabled() is True
    for v in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", v)
        assert cli._draft_only_enabled() is False
    monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    assert cli._draft_only_enabled() is False


@pytest.mark.parametrize("args_fn", [_send_args, _reply_args])
def test_transmit_refused(monkeypatch, args_fn):
    monkeypatch.setenv("EMAIL_DRAFT_ONLY", "1")
    calls = _guard_all_sends(monkeypatch)

    with pytest.raises(RuntimeError, match="draft-only mode"):
        cli._dispatch_email(args_fn(), Config())

    # Refused before any send function ran.
    assert calls == []


def test_draft_not_blocked_in_draft_only_mode(monkeypatch):
    monkeypatch.setenv("EMAIL_DRAFT_ONLY", "1")
    _guard_all_sends(monkeypatch)
    monkeypatch.setattr(gmail, "create_draft", lambda cfg, **kw: {"id": "draft-1", **kw})

    result = cli._dispatch_email(_draft_args(), Config())

    assert result["id"] == "draft-1"


@pytest.mark.parametrize("args_fn", [_send_args, _reply_args])
def test_send_reaches_gmail_when_env_unset(monkeypatch, args_fn):
    monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    reached = []
    monkeypatch.setattr(gmail, "send_email", lambda *a, **k: reached.append("send") or "sent")
    monkeypatch.setattr(gmail, "reply_to_email", lambda *a, **k: reached.append("reply") or "replied")

    result = cli._dispatch_email(args_fn(), Config())

    assert reached and result in ("sent", "replied")
