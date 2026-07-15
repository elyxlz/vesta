"""Gmail body extraction: MIME tree walk, HTML->text with links, idempotent save."""

import base64

from google_cli import gmail
from google_cli.config import Config


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _leaf(mime: str, text: str) -> dict:
    return {"mimeType": mime, "body": {"data": _b64(text)}}


# -- _get_body_text -----------------------------------------------------


def test_plain_text_leaf():
    payload = _leaf("text/plain", "hello world")
    assert gmail._get_body_text(payload) == "hello world"


def test_html_only_message_preserves_links():
    html = '<div>Hi <a href="https://example.com/deal">click here</a> now</div>'
    payload = _leaf("text/html", html)
    body = gmail._get_body_text(payload)
    assert "click here" in body
    assert "https://example.com/deal" in body  # href target preserved


def test_html_link_with_url_as_text_not_duplicated():
    html = '<a href="https://example.com">https://example.com</a>'
    payload = _leaf("text/html", html)
    body = gmail._get_body_text(payload)
    assert body.count("https://example.com") == 1


def test_multipart_alternative_prefers_plain():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            _leaf("text/plain", "plain version"),
            _leaf("text/html", "<p>html version</p>"),
        ],
    }
    assert gmail._get_body_text(payload) == "plain version"


def test_nested_multipart_mixed_falls_back_to_html():
    # multipart/mixed -> multipart/alternative -> only html present.
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    _leaf("text/html", '<p>Deal: <a href="https://x.io/y">buy</a></p>'),
                ],
            },
            {"mimeType": "application/pdf", "filename": "invoice.pdf", "body": {"attachmentId": "a1"}},
        ],
    }
    body = gmail._get_body_text(payload)
    assert "Deal:" in body and "buy" in body and "https://x.io/y" in body


def test_html_strips_script_and_style():
    html = "<style>.x{color:red}</style><p>visible</p><script>evil()</script>"
    body = gmail._html_to_text(html)
    assert "visible" in body
    assert "color:red" not in body and "evil" not in body


def test_empty_payload_returns_empty():
    assert gmail._get_body_text({"mimeType": "text/plain", "body": {}}) == ""


# -- idempotent save ----------------------------------------------------


def test_output_path_is_deterministic_per_message(tmp_path):
    cfg = Config(data_dir=tmp_path)
    p1 = gmail._prepare_email_output_path(cfg, "msg-123", "Hello there", None)
    p2 = gmail._prepare_email_output_path(cfg, "msg-123", "Hello there", None)
    assert p1 == p2  # same message -> same file, overwrite not accumulate


def test_get_email_overwrites_not_accumulates(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path)
    html = '<p>Body with <a href="https://example.com/z">link</a></p>'
    message = {
        "id": "msg-1",
        "threadId": "t-1",
        "snippet": "snip",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Sale"},
                {"name": "From", "value": "shop@example.com"},
                {"name": "To", "value": "me@gmail.com"},
                {"name": "Date", "value": "Sun, 12 Jul 2026 10:00:00 +0000"},
            ],
            "mimeType": "text/html",
            "body": {"data": _b64(html)},
        },
    }

    class _FakeMessages:
        def get(self, **kwargs):
            class _E:
                def execute(self_inner):
                    return message

            return _E()

    class _FakeUsers:
        def messages(self):
            return _FakeMessages()

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr(gmail.api, "gmail_service", lambda config: _FakeService())

    first = gmail.get_email(cfg, message_id="msg-1")
    second = gmail.get_email(cfg, message_id="msg-1")

    assert first["body_saved_to"] == second["body_saved_to"]
    saved = list((tmp_path / "emails").glob("*.txt"))
    assert len(saved) == 1  # only one file despite two fetches
    content = saved[0].read_text()
    assert "https://example.com/z" in content and "link" in content
    assert first["body_length"] > 0
