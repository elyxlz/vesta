"""EMAIL_DRAFT_ONLY hard send-disable guard in smtp_send.main().

The guard sits in main() before send() runs, so send / reply / forward invocations
are refused before any SMTP contact. Drafting (--draft) stays allowed.

The smtp module imports imap_tools (via the imap module), so a minimal stub is
registered first, which lets the guard be exercised without that dependency.
"""

import sys
import types

import pytest


def _install_stubs():
    """Register a minimal fake imap_tools so the smtp/imap modules import."""
    if "imap_tools" not in sys.modules:
        it = types.ModuleType("imap_tools")

        def _and(*_a, **_k):
            return None

        class MailBox:
            def __init__(self, *_a, **_k):
                pass

        class MailMessageFlags:
            DRAFT = "\\Draft"
            SEEN = "\\Seen"
            ANSWERED = "\\Answered"

        # The attribute mirrors the imap_tools API name.
        it.AND = _and
        it.MailBox = MailBox
        it.MailMessageFlags = MailMessageFlags
        sys.modules["imap_tools"] = it


_install_stubs()
from email_client import smtp as smtp_send


def _run(monkeypatch, argv, env):
    """Run smtp_send.main() with a patched send() recorder and given argv/env."""
    calls = []
    monkeypatch.setattr(smtp_send, "send", calls.append)
    if env is None:
        monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    else:
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", env)
    monkeypatch.setattr(sys, "argv", ["email-client-send", *argv])
    return calls


SEND = ["--to", "bob@x.com", "--subject", "Hi", "--body", "hello"]
REPLY = ["--reply-to-uid", "42", "--body", "thanks"]
FORWARD = ["--forward-uid", "42", "--to", "bob@x.com", "--body", "fyi"]


def test_helper_truthy_values(monkeypatch):
    for v in ("1", "true", "TRUE", "Yes", "  yes  "):
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", v)
        assert smtp_send._draft_only_enabled() is True
    for v in ("", "0", "false", "no", "off"):
        monkeypatch.setenv("EMAIL_DRAFT_ONLY", v)
        assert smtp_send._draft_only_enabled() is False
    monkeypatch.delenv("EMAIL_DRAFT_ONLY", raising=False)
    assert smtp_send._draft_only_enabled() is False


@pytest.mark.parametrize("argv", [SEND, REPLY, FORWARD], ids=["send", "reply", "forward"])
def test_transmit_refused_in_draft_only(monkeypatch, argv):
    calls = _run(monkeypatch, argv, env="1")
    with pytest.raises(SystemExit) as ei:
        smtp_send.main()
    # Non-zero exit with a message that mentions draft-only, and send() never ran.
    assert "draft-only" in str(ei.value)
    assert calls == []


def test_draft_still_works_in_draft_only(monkeypatch):
    calls = _run(monkeypatch, [*SEND, "--draft"], env="1")
    smtp_send.main()
    # send() was reached with draft=True.
    assert len(calls) == 1
    assert calls[0].draft is True


def test_dry_run_preview_allowed_in_draft_only(monkeypatch):
    calls = _run(monkeypatch, [*SEND, "--dry-run"], env="1")
    smtp_send.main()
    assert len(calls) == 1
    assert calls[0].dry_run is True


@pytest.mark.parametrize("argv", [SEND, REPLY, FORWARD], ids=["send", "reply", "forward"])
def test_send_reaches_send_when_env_unset(monkeypatch, argv):
    calls = _run(monkeypatch, argv, env=None)
    smtp_send.main()
    assert len(calls) == 1
    assert calls[0].draft is False
