"""fetch_original: the original's headers are safe to reuse in a reply or forward."""

import contextlib
import types

from email_client import smtp as smtp_send


def _fake_connect(message):
    @contextlib.contextmanager
    def connect(_account, initial_folder=None):
        yield types.SimpleNamespace(
            folder=types.SimpleNamespace(set=lambda _folder: None),
            fetch=lambda *_a, **_k: [message],
        )

    return connect


def test_folded_subject_is_unfolded_for_reply_and_forward(monkeypatch):
    message = types.SimpleNamespace(
        subject="Enrollment request for the autumn\r\n term",
        headers={"message-id": ("<m1@example.com>",)},
        from_values=types.SimpleNamespace(full="Sender <sender@example.com>"),
        to_values=[],
        cc_values=[],
        date_str="Mon, 1 Jan 2026 10:00:00 +0000",
        text="hello",
        html="",
    )
    monkeypatch.setattr(smtp_send, "connect", _fake_connect(message))

    orig = smtp_send.fetch_original(None, "INBOX", "1")

    assert orig["subject"] == "Enrollment request for the autumn term"
    assert smtp_send._re_subject(orig["subject"]) == "Re: Enrollment request for the autumn term"
    assert smtp_send._fwd_subject(orig["subject"]) == "Fwd: Enrollment request for the autumn term"
