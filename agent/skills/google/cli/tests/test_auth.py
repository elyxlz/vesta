"""Auth requires the user's own OAuth client (~/.google/credentials.json)."""

import json as _json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from google.auth.exceptions import RefreshError
from google_cli import auth
from google_cli.config import CALENDAR_SCOPES, GMAIL_SCOPES, SCOPES

# -- the default scope set -----------------------------------------------


def test_default_scope_set_is_exactly_mail_and_calendar():
    assert SCOPES == [
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/calendar",
    ]


def test_full_gmail_scope_replaces_modify_and_send():
    assert GMAIL_SCOPES == ["https://mail.google.com/"]
    assert "https://www.googleapis.com/auth/gmail.modify" not in SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" not in SCOPES


def test_calendar_scope_present():
    assert CALENDAR_SCOPES == ["https://www.googleapis.com/auth/calendar"]


# -- credentials.json is required ----------------------------------------


class _FakeFlow:
    """Stand-in for InstalledAppFlow that records which constructor was used."""

    @staticmethod
    def from_client_secrets_file(path, scopes):
        return {"via": "secrets_file", "path": path, "scopes": scopes}


def test_missing_credentials_file_is_a_clear_actionable_error(tmp_path):
    creds_file = tmp_path / "credentials.json"  # does NOT exist
    with pytest.raises(ValueError) as ei:
        auth._make_flow(creds_file, ["s"])
    msg = str(ei.value)
    assert str(creds_file) in msg
    assert "SETUP.md" in msg
    assert "email-client" in msg


def test_start_auth_flow_without_credentials_file_errors(tmp_path):
    with pytest.raises(ValueError, match=r"SETUP\.md"):
        auth.start_auth_flow(tmp_path / "credentials.json", ["s"])


def test_make_flow_uses_the_credentials_file(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "InstalledAppFlow", _FakeFlow)
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text('{"installed": {"client_id": "own-app"}}')
    flow = auth._make_flow(creds_file, ["s"])
    assert flow["via"] == "secrets_file"
    assert flow["path"] == str(creds_file)


# -- token refresh across the expiry boundary (regression) --------------
#
# Bug this guards: _save_token never persisted `expiry` and _load_token never
# restored it, so a reloaded Credentials had expiry=None -> creds.valid was
# always True -> get_credentials returned the stale access token and never
# refreshed. Every Gmail/Calendar call then 401'd ~1h after sign-in. All prior
# tests passed because none crossed the token-expiry boundary.


def _write_token(path, *, expiry_iso, token="stale-access"):
    path.write_text(
        _json.dumps(
            {
                "token": token,
                "refresh_token": "refresh-abc",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": "cid",
                "client_secret": "sec",
                "scopes": ["https://mail.google.com/"],
                **({"expiry": expiry_iso} if expiry_iso is not None else {}),
            }
        )
    )


def test_save_token_persists_expiry_and_load_restores_it(tmp_path):
    tok = tmp_path / "token.json"
    exp = datetime(2030, 1, 1, 12, 0, 0)

    creds = SimpleNamespace(
        token="t",
        refresh_token="r",
        token_uri="u",
        client_id="c",
        client_secret="s",
        scopes=["https://mail.google.com/"],
        expiry=exp,
    )
    auth._save_token(tok, creds)
    assert _json.loads(tok.read_text())["expiry"] == exp.isoformat()
    reloaded = auth._load_token(tok, ["https://mail.google.com/"])
    assert reloaded.expiry == exp


def _patch_refresh(monkeypatch):
    """Make creds.refresh() a no-op that just marks a fresh token, no network."""
    calls = {"n": 0}

    def fake_refresh(self, request):
        calls["n"] += 1
        self.token = "fresh-access"
        self.expiry = datetime.now() + timedelta(hours=1)

    monkeypatch.setattr(auth.Credentials, "refresh", fake_refresh, raising=True)
    monkeypatch.setattr(auth, "Request", object)
    return calls


def test_get_credentials_refreshes_when_expired(tmp_path, monkeypatch):
    tok = tmp_path / "token.json"
    _write_token(tok, expiry_iso=(datetime.now() - timedelta(hours=2)).isoformat())
    calls = _patch_refresh(monkeypatch)
    creds = auth.get_credentials(tok, ["https://mail.google.com/"])
    assert calls["n"] == 1
    assert creds.token == "fresh-access"
    # the refreshed token (with new expiry) is written back
    assert _json.loads(tok.read_text())["token"] == "fresh-access"


def test_get_credentials_refreshes_when_expiry_unknown(tmp_path, monkeypatch):
    # a token saved by the OLD code path: no expiry field at all.
    tok = tmp_path / "token.json"
    _write_token(tok, expiry_iso=None)
    calls = _patch_refresh(monkeypatch)
    creds = auth.get_credentials(tok, ["https://mail.google.com/"])
    assert calls["n"] == 1
    assert creds.token == "fresh-access"


def test_refresh_failure_tells_user_to_sign_in_again(tmp_path, monkeypatch):
    # A token minted under a different OAuth client (e.g. the old shared client)
    # cannot refresh under the user's own client; the error must say to re-run
    # sign-in rather than surface a raw RefreshError.
    tok = tmp_path / "token.json"
    _write_token(tok, expiry_iso=(datetime.now() - timedelta(hours=2)).isoformat())

    def failing_refresh(self, request):
        raise RefreshError("invalid_grant: Token has been expired or revoked.")

    monkeypatch.setattr(auth.Credentials, "refresh", failing_refresh, raising=True)
    monkeypatch.setattr(auth, "Request", object)
    with pytest.raises(ValueError, match="google auth login"):
        auth.get_credentials(tok, ["https://mail.google.com/"])
