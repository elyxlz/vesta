"""Unit tests for attachment listing / bulk download (mocked Graph calls)."""

import base64

import pytest
from microsoft_cli import email
from microsoft_cli.config import Config

_ATTACHMENTS = {
    "value": [
        {"id": "a1", "name": "report.pdf", "size": 3, "contentType": "application/pdf", "contentBytes": base64.b64encode(b"pdf").decode()},
        {"id": "a2", "name": "report.pdf", "size": 3, "contentType": "application/pdf", "contentBytes": base64.b64encode(b"two").decode()},
        {"id": "a3", "name": "ref-item", "size": 0, "contentType": "message/rfc822"},  # no contentBytes: skipped
    ]
}


@pytest.fixture
def patched(monkeypatch):
    def fake_account_id(account_email, cache_file):
        return "acct-1"

    def fake_request(conn, method, path, account_id=None, **kwargs):
        if method == "GET" and path.endswith("/attachments"):
            return _ATTACHMENTS
        return None

    monkeypatch.setattr(email.auth, "get_account_id_by_email", fake_account_id)
    monkeypatch.setattr(email.graph, "request", fake_request)


def test_list_attachments(patched):
    result = email.list_attachments(Config(), None, account_email="me@example.com", email_id="m1")
    assert [a["name"] for a in result] == ["report.pdf", "report.pdf", "ref-item"]


def test_download_all_dedupes_names_and_skips_non_file(patched, tmp_path):
    result = email.download_attachments(Config(), None, account_email="me@example.com", email_id="m1", out_dir=str(tmp_path))
    assert result["count"] == 2
    saved_paths = sorted(p.name for p in tmp_path.iterdir())
    assert saved_paths == ["report.pdf", "report_1.pdf"]
    assert (tmp_path / "report.pdf").read_bytes() == b"pdf"
    assert (tmp_path / "report_1.pdf").read_bytes() == b"two"
