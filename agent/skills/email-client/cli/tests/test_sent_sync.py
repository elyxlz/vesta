"""Gmail accounts must skip the sent-copy APPEND in smtp._sync_sent_message().

Gmail's SMTP server auto-saves every message sent through it to the account's
Sent folder, so the skill's own IMAP APPEND would leave two copies of each
sent message. _sync_sent_message() therefore returns before _append_message()
for gmail accounts unless EMAIL_CLIENT_FORCE_SENT_SYNC=1 is set.

The smtp module imports imap_tools (via the imap module), so a minimal stub is
registered first (same as test_draft_only.py), which lets the guard be
exercised without that dependency.
"""

import sys
import types
from email.message import EmailMessage


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

        class MailboxUidsError(Exception):
            pass

        # The attribute mirrors the imap_tools API name.
        it.AND = _and
        it.MailBox = MailBox
        it.MailMessageFlags = MailMessageFlags
        it.MailboxUidsError = MailboxUidsError
        sys.modules["imap_tools"] = it


_install_stubs()
from email_client import smtp as smtp_send


def _message():
    m = EmailMessage()
    m["From"] = "sender@example.com"
    m["To"] = "recipient@example.com"
    m["Subject"] = "ping"
    m.set_content("hello")
    return m


def _patch(monkeypatch, provider):
    """Patch provider resolution and record _append_message calls."""
    monkeypatch.delenv("EMAIL_CLIENT_FORCE_SENT_SYNC", raising=False)
    monkeypatch.setattr(smtp_send, "account_profile", lambda acc: (provider, {}))
    calls = []

    def _append(account, raw_bytes, *, role, profile_fallback, flags):
        calls.append({"account": account, "role": role, "fallback": profile_fallback})
        return True, "[Gmail]/Sent Mail"

    monkeypatch.setattr(smtp_send, "_append_message", _append)
    return calls


def test_gmail_skips_append(monkeypatch, capsys):
    calls = _patch(monkeypatch, "gmail")
    smtp_send._sync_sent_message("work", {"sent_folder": "[Gmail]/Sent Mail"}, _message())
    assert calls == []
    assert "skipped local append" in capsys.readouterr().out


def test_non_gmail_provider_still_appends(monkeypatch):
    calls = _patch(monkeypatch, "fastmail")
    smtp_send._sync_sent_message("personal", {"sent_folder": "Sent"}, _message())
    assert len(calls) == 1
    assert calls[0]["account"] == "personal"
    assert calls[0]["role"] == "sent"
    assert calls[0]["fallback"] == "Sent"


def test_gmail_force_env_restores_append(monkeypatch):
    calls = _patch(monkeypatch, "gmail")
    monkeypatch.setenv("EMAIL_CLIENT_FORCE_SENT_SYNC", "1")
    smtp_send._sync_sent_message("work", {"sent_folder": "[Gmail]/Sent Mail"}, _message())
    assert len(calls) == 1
    assert calls[0]["role"] == "sent"
