"""EMAIL_DRAFT_ONLY hard send-disable guard in cli._dispatch_email.

The guard sits at the command-dispatch layer, before _route picks a backend, so a
single check covers BOTH the Graph and OWA-REST transmit paths. Drafting stays allowed.
"""

from types import SimpleNamespace

import pytest

from microsoft_cli import cli, backend, email, owa_rest_commands
from microsoft_cli.config import Config


def _send_args(**over):
    base = dict(
        command="send",
        account="me@example.com",
        to=["bob@x.com"],
        subject="Hi",
        body="body",
        cc=None,
        bcc=None,
        attachments=None,
        html=False,
        backend=backend.GRAPH,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _reply_args(**over):
    base = dict(
        command="reply",
        account="me@example.com",
        email_id="orig-1",
        body="thanks",
        attachments=None,
        reply_all=False,
        html=False,
        backend=backend.GRAPH,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _forward_args(**over):
    base = dict(
        command="forward",
        account="me@example.com",
        email_id="orig-1",
        to=["bob@x.com"],
        body="fyi",
        cc=None,
        attachments=None,
        html=False,
        backend=backend.GRAPH,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _draft_args(**over):
    base = dict(
        command="draft",
        account="me@example.com",
        to=["bob@x.com"],
        subject="Hi",
        body="body",
        cc=None,
        bcc=None,
        attachments=None,
        reply_to_id=None,
        forward_id=None,
        backend=backend.GRAPH,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _guard_all_sends(monkeypatch):
    """Make every transmit function on BOTH backends explode if it's ever reached."""
    calls = []

    def boom(name):
        def _f(*a, **k):
            calls.append(name)
            raise AssertionError(f"{name} must not be called in draft-only mode")

        return _f

    for mod, prefix in ((email, "graph"), (owa_rest_commands, "rest")):
        monkeypatch.setattr(mod, "send_email", boom(f"{prefix}.send_email"))
        monkeypatch.setattr(mod, "reply_to_email", boom(f"{prefix}.reply_to_email"))
        monkeypatch.setattr(mod, "forward_email", boom(f"{prefix}.forward_email"))
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


@pytest.mark.parametrize("choice", [backend.GRAPH, backend.OWA_REST])
@pytest.mark.parametrize("args_fn", [_send_args, _reply_args, _forward_args])
def test_transmit_refused_both_backends(monkeypatch, args_fn, choice):
    monkeypatch.setenv("EMAIL_DRAFT_ONLY", "1")
    calls = _guard_all_sends(monkeypatch)

    with pytest.raises(RuntimeError, match="draft-only mode"):
        cli._dispatch_email(args_fn(backend=choice), Config(), client=None)

    # Refused before any backend send function ran.
    assert calls == []


def test_draft_still_works_in_draft_only_mode(monkeypatch):
    monkeypatch.setenv("EMAIL_DRAFT_ONLY", "1")
    _guard_all_sends(monkeypatch)
    monkeypatch.setattr(cli.owa_rest, "has_valid_token", lambda *a, **k: False)
    monkeypatch.setattr(email, "create_email_draft", lambda cfg, client, **kw: {"id": "draft-1", **kw})

    result = cli._dispatch_email(_draft_args(), Config(), client=None)

    assert result["id"] == "draft-1"


@pytest.mark.parametrize("args_fn", [_send_args, _reply_args, _forward_args])
def test_send_reaches_backend_when_env_unset(monkeypatch, args_fn):
    monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    monkeypatch.setattr(cli.owa_rest, "has_valid_token", lambda *a, **k: False)
    reached = []
    monkeypatch.setattr(email, "send_email", lambda *a, **k: reached.append("send") or "sent")
    monkeypatch.setattr(email, "reply_to_email", lambda *a, **k: reached.append("reply") or "replied")
    monkeypatch.setattr(email, "forward_email", lambda *a, **k: reached.append("forward") or "forwarded")

    result = cli._dispatch_email(args_fn(), Config(), client=None)

    assert reached and result in ("sent", "replied", "forwarded")
