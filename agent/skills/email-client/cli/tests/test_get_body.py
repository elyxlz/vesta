"""`get` returns readable text for an HTML-only mail, and says when it truncated."""

import argparse
import json

from email_client import imap

# A stylesheet longer than the slice the caller asks for, the shape a bulk sender
# emits: the message sits after it.
BULK_SENDER_SHAPED = (
    "<html><head><title>Receipt</title><style>"
    + "@font-face { font-family: X; src: url('https://cdn.example/x.woff2'); }" * 80
    + "</style></head><body><p>Hello Jane Doe</p>"
    "<p>You sent <b>50,00&nbsp;&euro;</b> to Someone</p>"
    "<table><tr><td>Transaction</td><td>ABC123</td></tr></table>"
    '<a href="https://pay.example/tx/ABC123">See details</a>'
    "</body></html>"
)


class _Folder:
    def __init__(self, box):
        self._box = box

    def set(self, name):
        self._box.folder_set = name


class _Msg:
    def __init__(self, text="", html=""):
        self.text = text
        self.html = html
        self.subject = "Receipt"
        self.date_str = "Sun, 09 Aug 2026 23:08:19 -0700"
        self.from_values = None
        self.from_ = "sender@example.com"
        self.to_values = ()
        self.to = ("jane@example.com",)


class _Box:
    def __init__(self, msg):
        self.folder = _Folder(self)
        self.folder_set = None
        self._msg = msg

    def fetch(self, criteria, mark_seen=False, limit=1):
        return [self._msg]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _run(monkeypatch, capsys, msg, body_chars=4000):
    monkeypatch.setattr(imap, "connect", lambda *a, **k: _Box(msg))
    args = argparse.Namespace(
        account=None, folder="INBOX", uid="1", body_chars=body_chars
    )
    imap.cmd_get(args)
    return json.loads(capsys.readouterr().out)


def test_html_only_body_is_flattened_to_text(monkeypatch, capsys):
    """The default slice must hold the message, not the stylesheet in front of it."""
    out = _run(monkeypatch, capsys, _Msg(html=BULK_SENDER_SHAPED))
    assert out["body_format"] == "html-to-text"
    assert "Hello Jane Doe" in out["body"]
    assert "You sent 50,00 € to Someone" in out["body"]
    assert "ABC123" in out["body"]
    assert "@font-face" not in out["body"]
    assert "<p>" not in out["body"]
    # <head> is markup, not message: its <title> merely repeats the subject.
    assert "Receipt" not in out["body"]


def test_html_body_keeps_link_targets(monkeypatch, capsys):
    out = _run(monkeypatch, capsys, _Msg(html=BULK_SENDER_SHAPED))
    assert "See details" in out["body"]
    assert "https://pay.example/tx/ABC123" in out["body"]


def test_plain_text_part_is_preferred_untouched(monkeypatch, capsys):
    out = _run(
        monkeypatch, capsys, _Msg(text="plain <b>wins</b>", html=BULK_SENDER_SHAPED)
    )
    assert out["body_format"] == "text"
    assert out["body"] == "plain <b>wins</b>"


def test_truncation_is_reported(monkeypatch, capsys):
    out = _run(monkeypatch, capsys, _Msg(text="x" * 50), body_chars=10)
    assert out["body"] == "x" * 10
    assert out["body_truncated"] is True
    assert out["body_chars_total"] == 50


def test_untruncated_body_carries_no_truncation_keys(monkeypatch, capsys):
    """The flag has to be able to stay absent, or its presence proves nothing."""
    out = _run(monkeypatch, capsys, _Msg(text="short"))
    assert "body_truncated" not in out
    assert "body_chars_total" not in out


def test_truncation_is_measured_after_flattening(monkeypatch, capsys):
    """A body is 32k of markup and 1k of text; the flag must describe what is returned."""
    out = _run(monkeypatch, capsys, _Msg(html=BULK_SENDER_SHAPED))
    assert len(BULK_SENDER_SHAPED) > 4000
    assert "body_truncated" not in out


def test_empty_message_is_not_an_error(monkeypatch, capsys):
    out = _run(monkeypatch, capsys, _Msg())
    assert out["body"] == ""
    assert out["body_format"] == "text"


def test_script_and_style_text_is_dropped():
    assert imap._html_to_text("<script>bad()</script>keep") == "keep"
    assert imap._html_to_text("<style>.a{color:red}</style>keep") == "keep"


def test_entities_are_decoded():
    assert imap._html_to_text("&amp; &lt; &gt;") == "& < >"


def test_block_tags_become_line_breaks():
    assert imap._html_to_text("<p>one</p><p>two</p>").splitlines()[0] == "one"
    assert "two" in imap._html_to_text("<p>one</p><p>two</p>").splitlines()[-1]
    assert imap._html_to_text("a<br>b").splitlines() == ["a", "b"]


def test_table_cells_do_not_concatenate():
    """Two adjacent values must stay two tokens, or neither can be searched for."""
    out = imap._html_to_text("<table><tr><td>Transaction</td><td>ABC123</td></tr></table>")
    assert "TransactionABC123" not in out
    assert "ABC123" in out


def test_nbsp_folds_to_a_plain_space():
    assert imap._html_to_text("50,00&nbsp;&euro;") == "50,00 \u20ac"
