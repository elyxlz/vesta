"""Unit tests for the OWA REST transport.

Covers:
- Key-case adapter (camel<->Pascal round-trip, @-key preservation, $select translation)
- Token file management (has_valid_token, load_token, save_token, jwt_exp)
- REST transport operations against mocked httpx responses
- Dispatcher Graph->OWA(REST) fallback path via backend.run with OWA_REST choice
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from microsoft_cli import backend, owa_rest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_token(exp: float) -> str:
    """Build a minimal fake JWT with the given exp claim."""
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload_bytes = json.dumps({"exp": exp, "aud": "https://outlook.office.com"}).encode()
    payload = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    return f"{header}.{payload}.fake_sig"


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://outlook.office.com/api/v2.0/me/messages")
    resp = httpx.Response(status, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


class _FakeConfig:
    """Minimal config stand-in with a data_dir."""

    def __init__(self, tmp_path: Path) -> None:
        self.data_dir = tmp_path


# ---------------------------------------------------------------------------
# Case adapter tests
# ---------------------------------------------------------------------------


def test_to_pascal_converts_first_letter():
    assert owa_rest._to_pascal("subject") == "Subject"
    assert owa_rest._to_pascal("emailAddress") == "EmailAddress"
    assert owa_rest._to_pascal("id") == "Id"


def test_to_camel_converts_first_letter():
    assert owa_rest._to_camel("Subject") == "subject"
    assert owa_rest._to_camel("EmailAddress") == "emailAddress"
    assert owa_rest._to_camel("Id") == "id"


def test_conv_keys_camel_to_pascal():
    obj = {"subject": "Hello", "from": {"emailAddress": {"address": "a@b.com"}}}
    out = owa_rest.conv_keys(obj, owa_rest._to_pascal)
    assert out == {"Subject": "Hello", "From": {"EmailAddress": {"Address": "a@b.com"}}}


def test_conv_keys_pascal_to_camel():
    obj = {"Subject": "Hello", "From": {"EmailAddress": {"Address": "a@b.com"}}}
    out = owa_rest.conv_keys(obj, owa_rest._to_camel)
    assert out == {"subject": "Hello", "from": {"emailAddress": {"address": "a@b.com"}}}


def test_conv_keys_round_trip():
    original = {"subject": "test", "toRecipients": [{"emailAddress": {"address": "x@y.com"}}]}
    up = owa_rest.conv_keys(original, owa_rest._to_pascal)
    down = owa_rest.conv_keys(up, owa_rest._to_camel)
    assert down == original


def test_conv_keys_preserves_at_prefix():
    obj = {"@odata.nextLink": "https://next", "@odata.context": "ctx", "value": []}
    out = owa_rest.conv_keys(obj, owa_rest._to_pascal)
    assert "@odata.nextLink" in out
    assert "@odata.context" in out
    assert "value" not in out  # "value" -> "Value"
    out2 = owa_rest.conv_keys(obj, owa_rest._to_camel)
    assert "@odata.nextLink" in out2


def test_conv_keys_handles_lists():
    obj = [{"subject": "A"}, {"subject": "B"}]
    out = owa_rest.conv_keys(obj, owa_rest._to_pascal)
    assert out == [{"Subject": "A"}, {"Subject": "B"}]


def test_select_to_pascal():
    result = owa_rest._select_to_pascal("id,subject,receivedDateTime,from")
    assert result == "Id,Subject,ReceivedDateTime,From"


def test_select_to_pascal_trims_spaces():
    result = owa_rest._select_to_pascal("id, subject , from")
    assert result == "Id,Subject,From"


# ---------------------------------------------------------------------------
# JWT exp decoding
# ---------------------------------------------------------------------------


def test_jwt_exp_decodes_correctly():
    exp = 9999999999.0
    token = _make_token(exp)
    assert owa_rest.jwt_exp(token) == exp


def test_jwt_exp_raises_on_non_jwt():
    with pytest.raises(ValueError):
        owa_rest.jwt_exp("notajwt")


# ---------------------------------------------------------------------------
# Token file management
# ---------------------------------------------------------------------------


def test_has_valid_token_returns_false_when_no_file(tmp_path):
    cfg = _FakeConfig(tmp_path)
    assert owa_rest.has_valid_token("user@example.com", cfg) is False


def test_has_valid_token_returns_false_when_expired(tmp_path):
    cfg = _FakeConfig(tmp_path)
    expired = time.time() - 3600
    owa_rest.save_token("user@example.com", cfg, token=_make_token(expired), expires_at=expired)
    assert owa_rest.has_valid_token("user@example.com", cfg) is False


def test_has_valid_token_returns_true_for_fresh_token(tmp_path):
    cfg = _FakeConfig(tmp_path)
    future = time.time() + 7200
    owa_rest.save_token("user@example.com", cfg, token=_make_token(future), expires_at=future)
    assert owa_rest.has_valid_token("user@example.com", cfg) is True


def test_load_token_raises_when_missing(tmp_path):
    cfg = _FakeConfig(tmp_path)
    with pytest.raises(owa_rest.OwaRestNoToken, match="owa-login"):
        owa_rest.load_token("user@example.com", cfg)


def test_load_token_raises_when_expired(tmp_path):
    cfg = _FakeConfig(tmp_path)
    expired = time.time() - 3600
    owa_rest.save_token("user@example.com", cfg, token="tok", expires_at=expired)
    with pytest.raises(owa_rest.OwaRestNoToken, match="expired"):
        owa_rest.load_token("user@example.com", cfg)


def test_load_token_returns_token_when_valid(tmp_path):
    cfg = _FakeConfig(tmp_path)
    future = time.time() + 7200
    owa_rest.save_token("user@example.com", cfg, token="my-secret-token", expires_at=future)
    assert owa_rest.load_token("user@example.com", cfg) == "my-secret-token"


def test_save_token_creates_parent_dirs(tmp_path):
    cfg = _FakeConfig(tmp_path / "deep" / "nested")
    future = time.time() + 3600
    owa_rest.save_token("a@b.com", cfg, token="tok", expires_at=future)
    p = owa_rest._token_path("a@b.com", cfg)
    assert p.exists()
    stored = json.loads(p.read_text())
    assert stored["token"] == "tok"
    assert stored["expires_at"] == pytest.approx(future)


# ---------------------------------------------------------------------------
# REST transport: list_messages
# ---------------------------------------------------------------------------


def _mock_client(json_response: dict, status: int = 200) -> httpx.Client:
    """Return a mock httpx.Client whose get() returns the given JSON."""
    mock = MagicMock(spec=httpx.Client)
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = json_response
    resp.raise_for_status = MagicMock()
    mock.get.return_value = resp
    mock.post.return_value = resp
    mock.patch.return_value = resp
    mock.delete.return_value = resp
    return mock


def _patched_token(tmp_path: Path, account: str = "user@example.com") -> _FakeConfig:
    cfg = _FakeConfig(tmp_path)
    owa_rest.save_token(account, cfg, token="test-tok", expires_at=time.time() + 7200)
    return cfg


def test_list_messages_returns_camel_cased_items(tmp_path):
    cfg = _patched_token(tmp_path)
    client = _mock_client({"value": [{"Id": "m1", "Subject": "Hello", "From": {"EmailAddress": {"Address": "a@b.com"}}}]})
    result = owa_rest.list_messages(client, "user@example.com", cfg, folder="inbox", limit=5)
    assert len(result) == 1
    assert result[0]["id"] == "m1"
    assert result[0]["subject"] == "Hello"
    assert result[0]["from"]["emailAddress"]["address"] == "a@b.com"


def test_list_messages_uses_correct_folder_path(tmp_path):
    cfg = _patched_token(tmp_path)
    client = _mock_client({"value": []})
    owa_rest.list_messages(client, "user@example.com", cfg, folder="sent", limit=5)
    call_args = client.get.call_args
    assert "/me/mailfolders/sentitems/messages" in call_args[0][0]


def test_list_messages_folder_alias_deleted(tmp_path):
    cfg = _patched_token(tmp_path)
    client = _mock_client({"value": []})
    owa_rest.list_messages(client, "user@example.com", cfg, folder="deleted", limit=5)
    call_args = client.get.call_args
    assert "deleteditems" in call_args[0][0]


def test_list_messages_passes_select_in_pascal_case(tmp_path):
    cfg = _patched_token(tmp_path)
    client = _mock_client({"value": []})
    owa_rest.list_messages(client, "user@example.com", cfg)
    # params are passed as keyword arg to client.get
    call_kwargs = client.get.call_args.kwargs
    params = call_kwargs.get("params") or {}
    select = params.get("$select", "")
    # After _select_to_pascal, camelCase fields become PascalCase
    assert "Subject" in select
    assert "ReceivedDateTime" in select


def test_list_messages_paginates_via_next_link(tmp_path):
    cfg = _patched_token(tmp_path)
    mock = MagicMock(spec=httpx.Client)
    page1_resp = MagicMock()
    page1_resp.status_code = 200
    page1_resp.raise_for_status = MagicMock()
    page1_resp.json.return_value = {
        "value": [{"Id": "m1", "Subject": "Page1"}],
        "@odata.nextLink": f"{owa_rest.OWA_REST_BASE}/me/mailfolders/inbox/messages?$skip=1",
    }
    page2_resp = MagicMock()
    page2_resp.status_code = 200
    page2_resp.raise_for_status = MagicMock()
    page2_resp.json.return_value = {"value": [{"Id": "m2", "Subject": "Page2"}]}
    mock.get.side_effect = [page1_resp, page2_resp]

    result = owa_rest.list_messages(mock, "user@example.com", cfg, folder="inbox", limit=10)
    assert len(result) == 2
    assert result[0]["id"] == "m1"
    assert result[1]["id"] == "m2"


# ---------------------------------------------------------------------------
# REST transport: send_message
# ---------------------------------------------------------------------------


def test_send_message_posts_pascal_cased_body(tmp_path):
    cfg = _patched_token(tmp_path)
    resp = MagicMock()
    resp.status_code = 202
    resp.raise_for_status = MagicMock()
    resp.content = b""
    client = MagicMock(spec=httpx.Client)
    client.post.return_value = resp

    result = owa_rest.send_message(client, "user@example.com", cfg, to=["b@c.com"], subject="Hi", body="Hello")
    assert result == {"status": "sent"}

    call_kwargs = client.post.call_args[1]
    posted_body = call_kwargs["json"]
    # The request body must be PascalCase (conv_keys applied to_pascal)
    assert "Message" in posted_body
    assert "Subject" in posted_body["Message"]
    assert posted_body["Message"]["Subject"] == "Hi"


# ---------------------------------------------------------------------------
# REST transport: get_message
# ---------------------------------------------------------------------------


def test_get_message_returns_camelcase(tmp_path):
    cfg = _patched_token(tmp_path)
    client = _mock_client({"Id": "m99", "Subject": "Test", "Body": {"ContentType": "Text", "Content": "body text"}})
    result = owa_rest.get_message(client, "user@example.com", cfg, item_id="m99")
    assert result["id"] == "m99"
    assert result["subject"] == "Test"
    assert result["body"]["contentType"] == "Text"


# ---------------------------------------------------------------------------
# REST transport: calendar list_events
# ---------------------------------------------------------------------------


def test_list_events_returns_camelcase_events(tmp_path):
    cfg = _patched_token(tmp_path)
    client = _mock_client(
        {
            "value": [
                {
                    "Id": "e1",
                    "Subject": "Standup",
                    "Start": {"DateTime": "2026-07-07T10:00:00Z", "TimeZone": "UTC"},
                    "End": {"DateTime": "2026-07-07T10:30:00Z", "TimeZone": "UTC"},
                }
            ]
        }
    )
    result = owa_rest.list_events(client, "user@example.com", cfg, start_utc="2026-07-07T00:00:00Z", end_utc="2026-07-14T00:00:00Z")
    assert len(result) == 1
    ev = result[0]
    assert ev["id"] == "e1"
    assert ev["subject"] == "Standup"
    assert ev["start"]["dateTime"] == "2026-07-07T10:00:00Z"


# ---------------------------------------------------------------------------
# REST transport: 401 raises HTTPStatusError (dispatcher sees permission failure)
# ---------------------------------------------------------------------------


def test_get_raises_http_status_error_on_401(tmp_path):
    cfg = _patched_token(tmp_path)
    mock = MagicMock(spec=httpx.Client)
    resp = MagicMock()
    resp.status_code = 401
    resp.raise_for_status.side_effect = _http_error(401)
    mock.get.return_value = resp

    with pytest.raises(httpx.HTTPStatusError):
        owa_rest.list_messages(mock, "user@example.com", cfg)


# ---------------------------------------------------------------------------
# Dispatcher: backend.run with OWA_REST choice
# ---------------------------------------------------------------------------


def test_force_owa_rest_calls_rest_fn():
    called = {"graph": False, "ews": False, "rest": False}

    def graph_fn():
        called["graph"] = True
        return "graph"

    def ews_fn():
        called["ews"] = True
        return "ews"

    def rest_fn():
        called["rest"] = True
        return "rest"

    result = backend.run(backend.OWA_REST, graph_fn, ews_fn, rest_fn)
    assert result == "rest"
    assert called["graph"] is False
    assert called["ews"] is False
    assert called["rest"] is True


def test_force_owa_rest_without_rest_fn_raises():
    with pytest.raises(ValueError, match="REST"):
        backend.run(backend.OWA_REST, lambda: "g", lambda: "e")


def test_auto_falls_back_to_ows_fn_on_permission_error():
    """auto: Graph 403 -> ewa_fn (existing OWA fallback, unchanged)."""

    def graph_fn():
        raise _http_error(403)

    result = backend.run(backend.AUTO, graph_fn, lambda: "ews-result")
    assert result == "ews-result"


def test_owa_rest_constant_value():
    assert backend.OWA_REST == "owa-rest"


# ---------------------------------------------------------------------------
# OwaRestNoToken is a RuntimeError subclass (dispatcher-compatible)
# ---------------------------------------------------------------------------


def test_owa_rest_no_token_is_runtime_error():
    err = owa_rest.OwaRestNoToken("needs login")
    assert isinstance(err, RuntimeError)


# ---------------------------------------------------------------------------
# delete_by_sender filters by exact address
# ---------------------------------------------------------------------------


def test_delete_by_sender_skips_non_matching(tmp_path):
    cfg = _patched_token(tmp_path)

    search_resp = MagicMock()
    search_resp.status_code = 200
    search_resp.raise_for_status = MagicMock()
    search_resp.json.return_value = {
        "value": [
            {"Id": "m1", "From": {"EmailAddress": {"Address": "spam@evil.com"}}},
            {"Id": "m2", "From": {"EmailAddress": {"Address": "legit@good.com"}}},
        ]
    }
    delete_resp = MagicMock()
    delete_resp.status_code = 204
    delete_resp.raise_for_status = MagicMock()
    delete_resp.content = b""

    client = MagicMock(spec=httpx.Client)
    client.get.return_value = search_resp
    client.delete.return_value = delete_resp

    result = owa_rest.delete_by_sender(client, "user@example.com", cfg, sender="spam@evil.com")
    assert result["deleted_count"] == 1
    assert result["deleted_ids"] == ["m1"]
    # Only the spam message was deleted
    assert client.delete.call_count == 1
