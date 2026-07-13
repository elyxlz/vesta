"""Behavior-locking tests for the Enable Banking HTTP client (faked httpx)."""

import json

import pytest

from finance_cli import enablebanking as eb


class FakeResponse:
    def __init__(self, payload, status_code=200, is_error=False, content=b"x"):
        self._payload = payload
        self.status_code = status_code
        self.is_error = is_error
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def http(monkeypatch):
    """Capture every outgoing request and feed queued responses.

    Patches both the per-verb httpx helpers and httpx.request so the locks hold
    regardless of which transport seam the client uses internally.
    """
    calls: list[dict] = []
    responses: list[FakeResponse] = []

    def record(method, url, headers=None, params=None, json=None):
        # Snapshot params: get_transactions mutates the same dict across pagination
        # calls, so storing the reference would make every recorded call reflect
        # the dict's final state instead of what was sent at call time.
        calls.append({"method": method, "url": url, "headers": headers, "params": dict(params) if params is not None else params, "json": json})
        return responses.pop(0)

    def fake_request(method, url, headers=None, params=None, json=None, timeout=None, **kw):
        return record(method, url, headers=headers, params=params, json=json)

    def fake_get(url, headers=None, params=None, timeout=None, **kw):
        return record("GET", url, headers=headers, params=params)

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        return record("POST", url, headers=headers, json=json)

    def fake_delete(url, headers=None, timeout=None, **kw):
        return record("DELETE", url, headers=headers)

    monkeypatch.setattr(eb.httpx, "request", fake_request)
    monkeypatch.setattr(eb.httpx, "get", fake_get)
    monkeypatch.setattr(eb.httpx, "post", fake_post)
    monkeypatch.setattr(eb.httpx, "delete", fake_delete)
    monkeypatch.setattr(eb, "_make_jwt", lambda app_id, key_path: "faketoken")
    return calls, responses


CONF = {"app_id": "app-1", "key_path": "/tmp/key.pem", "session_id": "sess-9", "aspsp_name": "", "aspsp_country": ""}


def test_get_balances_unwraps_list_response(http):
    calls, responses = http
    responses.append(FakeResponse([{"balance_amount": {"amount": "10"}}]))
    out = eb.get_balances(CONF, "acct-1")
    assert out == [{"balance_amount": {"amount": "10"}}]
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://api.enablebanking.com/accounts/acct-1/balances"
    assert calls[0]["headers"] == {"Authorization": "Bearer faketoken", "Content-Type": "application/json"}


def test_get_balances_unwraps_dict_response(http):
    calls, responses = http
    responses.append(FakeResponse({"balances": [{"x": 1}]}))
    out = eb.get_balances(CONF, "acct-1")
    assert out == [{"x": 1}]


def test_get_transactions_paginates_via_continuation_key(http):
    calls, responses = http
    responses.append(FakeResponse({"transactions": [{"id": "a"}], "continuation_key": "k1"}))
    responses.append(FakeResponse({"transactions": [{"id": "b"}]}))
    out = eb.get_transactions(CONF, "acct-1", date_from="2026-01-01", date_to="2026-02-01")
    assert out == [{"id": "a"}, {"id": "b"}]
    assert calls[0]["params"] == {"date_from": "2026-01-01", "date_to": "2026-02-01"}
    assert calls[1]["params"] == {"date_from": "2026-01-01", "date_to": "2026-02-01", "continuation_key": "k1"}
    assert calls[0]["url"] == "https://api.enablebanking.com/accounts/acct-1/transactions"


def test_initiate_auth_posts_auth_body_and_returns_url_state(http):
    calls, responses = http
    responses.append(FakeResponse({"url": "https://bank/auth"}))
    url, state = eb.initiate_auth(CONF)
    assert url == "https://bank/auth"
    assert isinstance(state, str) and state
    body = calls[0]["json"]
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.enablebanking.com/auth"
    assert body["aspsp"] == {"name": eb.ASPSP_NAME, "country": eb.ASPSP_COUNTRY}
    assert body["state"] == state
    assert body["redirect_url"] == eb.REDIRECT_URL
    assert body["psu_type"] == "personal"
    assert "valid_until" in body["access"]


def test_exchange_code_posts_sessions(http):
    calls, responses = http
    responses.append(FakeResponse({"session_id": "s1", "accounts": []}))
    out = eb.exchange_code(CONF, "the-code")
    assert out == {"session_id": "s1", "accounts": []}
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://api.enablebanking.com/sessions"
    assert calls[0]["json"] == {"code": "the-code"}


def test_get_session_gets_by_id(http):
    calls, responses = http
    responses.append(FakeResponse({"status": "AUTHORIZED"}))
    out = eb.get_session(CONF)
    assert out == {"status": "AUTHORIZED"}
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://api.enablebanking.com/sessions/sess-9"


def test_revoke_session_deletes_empty_body_returns_ok(http):
    calls, responses = http
    responses.append(FakeResponse(None, content=b""))
    out = eb.revoke_session(CONF)
    assert out == {"status": "ok"}
    assert calls[0]["method"] == "DELETE"
    assert calls[0]["url"] == "https://api.enablebanking.com/sessions/sess-9"


def test_error_response_exits(http, capsys):
    _, responses = http
    responses.append(FakeResponse({"detail": "bad"}, status_code=400, is_error=True))
    with pytest.raises(SystemExit) as exc:
        eb.get_session(CONF)
    assert exc.value.code == 1
    err = json.loads(capsys.readouterr().err)
    assert err["status"] == 400
    assert err["error"] == "Enable Banking API error (GET /sessions/sess-9)"
