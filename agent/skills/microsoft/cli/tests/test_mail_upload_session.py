"""Large mail attachments: the upload session PUT carries no bearer token, and a failed
build deletes the half-built draft."""

import httpx
import pytest
from microsoft_cli import email, graph
from microsoft_cli.config import Config

UPLOAD_URL = "https://outlook.example/api/gv1.0/AttachmentSessions('s1')?authtoken=x"


def _conn(handler):
    return graph.GraphConn(httpx.Client(transport=httpx.MockTransport(handler)), None, [], "https://graph.example/v1.0")


def test_upload_session_puts_chunks_without_authorization(monkeypatch):
    monkeypatch.setattr(graph, "get_token", lambda *a, **k: "tok")
    puts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            assert request.headers["Authorization"] == "Bearer tok"
            return httpx.Response(201, json={"uploadUrl": UPLOAD_URL})
        puts.append(request)
        end = int(request.headers["Content-Range"].split("-")[1].split("/")[0])
        return httpx.Response(201) if end == 24 else httpx.Response(200, json={"nextExpectedRanges": [f"{end + 1}-"]})

    graph.upload_large_mail_attachment(_conn(handler), 10, "m1", "big.pdf", b"x" * 25)

    assert [r.headers["Content-Range"] for r in puts] == ["bytes 0-9/25", "bytes 10-19/25", "bytes 20-24/25"]
    assert all("Authorization" not in r.headers for r in puts)


@pytest.mark.parametrize("command", ["reply", "draft"])
def test_failed_upload_deletes_the_half_built_draft(monkeypatch, tmp_path, command):
    calls = []

    def fake_request(conn, method, path, account_id=None, **kwargs):
        calls.append((method, path))
        if path.endswith("/createReply") or path == "/me/messages":
            return {"id": "d1"}
        if method == "GET":
            return {"body": {"contentType": "html", "content": "q"}, "toRecipients": [], "from": None}
        return None

    def failing_upload(*_args, **_kwargs):
        raise httpx.HTTPStatusError("401", request=httpx.Request("PUT", UPLOAD_URL), response=httpx.Response(401))

    monkeypatch.setattr(email.auth, "get_account_id_by_email", lambda *_a: "acct-1")
    monkeypatch.setattr(email.graph, "request", fake_request)
    monkeypatch.setattr(email.graph, "upload_mail_attachment_cfg", failing_upload)
    monkeypatch.setattr(email, "LARGE_ATTACHMENT_THRESHOLD", 1)
    attachment = tmp_path / "big.pdf"
    attachment.write_bytes(b"pdf")
    config = Config(data_dir=tmp_path)

    with pytest.raises(httpx.HTTPStatusError):
        if command == "reply":
            email.reply_to_email(config, None, account_email="me@example.com", email_id="m1", body="hi", attachments=[str(attachment)])
        else:
            mail = email.MailDraft(to=["bob@example.com"], subject="s", body="b", attachments=[str(attachment)])
            email.create_email_draft(config, None, account_email="me@example.com", mail=mail)

    assert calls[-1] == ("DELETE", "/me/messages/d1")
    assert ("POST", "/me/messages/d1/send") not in calls
