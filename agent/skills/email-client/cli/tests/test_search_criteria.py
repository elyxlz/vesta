"""`search --query` sends the query as given and falls back to a phrase search only on BAD."""

import argparse
import imaplib

import pytest
from email_client import imap
from imap_tools import AND


class _Folder:
    def __init__(self, box):
        self._box = box

    def set(self, name):
        self._box.folder_set = name


class _Box:
    """Accepts criteria the fake server considers valid, raises IMAP4.error on the rest."""

    def __init__(self, valid, *, abort_on_first=False):
        self._valid = valid
        self._abort_on_first = abort_on_first
        self.sent = []
        self.charsets = []
        self.folder = _Folder(self)
        self.folder_set = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch(self, criteria, charset="US-ASCII", **kw):
        self.sent.append(criteria)
        self.charsets.append(charset)
        if self._abort_on_first and len(self.sent) == 1:
            raise imaplib.IMAP4.abort("connection dropped")
        if criteria not in self._valid:
            raise imaplib.IMAP4.error("UID command error: BAD [b'Could not parse command']")
        return []


def _run(monkeypatch, box, query):
    monkeypatch.setattr(imap, "connect", lambda *a, **k: box)
    args = argparse.Namespace(query=query, folder="INBOX", limit=5, account=None)
    imap.cmd_search(args)


@pytest.mark.parametrize(
    "query",
    [
        'SUBJECT "invoice"',
        "SUBJECT invoice",
        "FROM billing@example.com",
        "HEADER Message-ID abc",
        'X-GM-RAW "has:attachment"',
        "UNSEEN",
        "LARGER 10000",
        'SINCE 1-Aug-2026 SUBJECT "receipt"',
    ],
)
def test_valid_criteria_are_sent_untouched_and_never_retried(monkeypatch, query):
    box = _Box(valid={query})
    _run(monkeypatch, box, query)
    assert box.sent == [query]


@pytest.mark.parametrize("query", ["job alert", "New jobs posted", "To do list", "quarterly report"])
def test_a_rejected_query_retries_as_a_phrase(monkeypatch, query):
    box = _Box(valid={AND(text=query)})
    _run(monkeypatch, box, query)
    assert box.sent == [query, AND(text=query)]


def test_a_dropped_connection_is_not_treated_as_a_bad_query(monkeypatch):
    """IMAP4.abort subclasses IMAP4.error, so catching only the parent would retry a network
    failure as a phrase search and report an empty result as if it were an answer."""
    box = _Box(valid={"UNSEEN"}, abort_on_first=True)
    with pytest.raises(imaplib.IMAP4.abort):
        _run(monkeypatch, box, "UNSEEN")
    assert len(box.sent) == 1


def test_a_query_the_server_rejects_twice_exits_with_a_message(monkeypatch):
    box = _Box(valid=set())
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, box, "hopeless")
    assert "hopeless" in str(excinfo.value)


def test_non_ascii_queries_request_utf8(monkeypatch):
    """imap_tools encodes criteria with the given charset, so US-ASCII raises UnicodeEncodeError
    before the query reaches the server."""
    box = _Box(valid={AND(text="café")})
    _run(monkeypatch, box, "café")
    assert box.charsets == ["UTF-8", "UTF-8"]


def test_ascii_queries_keep_the_default_charset(monkeypatch):
    box = _Box(valid={"UNSEEN"})
    _run(monkeypatch, box, "UNSEEN")
    assert box.charsets == ["US-ASCII"]
