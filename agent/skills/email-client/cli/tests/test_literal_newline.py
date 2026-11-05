"""send() refuses a --body whose only line breaks are a typed backslash-n.

The smtp module imports imap_tools, so a minimal stub is registered first, which is
what lets this module run on its own.
"""

import sys
import types

import pytest


def _install_imap_tools_stub():
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
            FLAGGED = "\\Flagged"

        class MailboxUidsError(Exception):
            pass

        it.AND = _and
        it.MailBox = MailBox
        it.MailMessageFlags = MailMessageFlags
        it.MailboxUidsError = MailboxUidsError
        sys.modules["imap_tools"] = it


_install_imap_tools_stub()
from email_client import smtp as smtp_send


class _PastGuardError(Exception):
    pass


def _send(monkeypatch, body):
    def _resolve(_account):
        raise _PastGuardError

    monkeypatch.setattr(smtp_send, "resolve_account", _resolve)
    smtp_send.send(smtp_send.SendRequest(to="bob@example.com", subject="Hi", body=body))


def test_literal_backslash_n_only_is_refused(monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _send(monkeypatch, "first line\\n\\nsecond line")
    assert "literal backslash-n" in str(exc.value)


def test_real_newlines_are_accepted(monkeypatch):
    with pytest.raises(_PastGuardError):
        _send(monkeypatch, "first line\n\nsecond line")


def test_real_newline_with_literal_backslash_n_is_accepted(monkeypatch):
    with pytest.raises(_PastGuardError):
        _send(monkeypatch, "Saved to:\nC:\\new\\report.txt")
