"""Auth reuses Thunderbird's published client by default; credentials.json overrides (Parts 1 & 2)."""

import json as _json
from datetime import datetime, timedelta

import pytest

from google_cli import auth, thunderbird_client
from google_cli.config import CALENDAR_SCOPES, GMAIL_SCOPES, MEET_SCOPE, SCOPES


# -- Part 2: the default scope set --------------------------------------


def test_default_scope_set_is_exactly_mail_and_calendar():
    assert SCOPES == [
        "https://mail.google.com/",
        "https://www.googleapis.com/auth/calendar",
    ]


def test_full_gmail_scope_replaces_modify_and_send():
    assert GMAIL_SCOPES == ["https://mail.google.com/"]
    assert "https://www.googleapis.com/auth/gmail.modify" not in SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" not in SCOPES


def test_meet_scope_dropped_from_default_set():
    assert MEET_SCOPE == "https://www.googleapis.com/auth/meetings.space.created"
    assert MEET_SCOPE not in SCOPES


def test_calendar_scope_present():
    assert CALENDAR_SCOPES == ["https://www.googleapis.com/auth/calendar"]


# -- Part 1: build_client_config reuses the Thunderbird client ----------


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    # No cache -> resolver returns the hardcoded Thunderbird constants (the floor).
    monkeypatch.setenv("GOOGLE_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GOOGLE_NO_DYNAMIC_CLIENT", raising=False)
    return tmp_path


def test_build_client_config_is_thunderbird_installed_client():
    cfg = auth.build_client_config()
    assert set(cfg.keys()) == {"installed"}
    inst = cfg["installed"]
    assert inst["client_id"] == thunderbird_client.THUNDERBIRD_GOOGLE_CLIENT_ID
    assert inst["client_secret"] == thunderbird_client.THUNDERBIRD_GOOGLE_CLIENT_SECRET
    assert inst["auth_uri"] == "https://accounts.google.com/o/oauth2/v2/auth"
    assert inst["token_uri"] == "https://oauth2.googleapis.com/token"
    assert "http://127.0.0.1" in inst["redirect_uris"]


# -- Part 1: _make_flow dispatch (client_config vs credentials.json) ----


class _FakeFlow:
    """Stand-in for InstalledAppFlow that records which constructor was used."""

    @staticmethod
    def from_client_config(client_config, scopes):
        return {"via": "client_config", "config": client_config, "scopes": scopes}

    @staticmethod
    def from_client_secrets_file(path, scopes):
        return {"via": "secrets_file", "path": path, "scopes": scopes}


def test_make_flow_defaults_to_in_memory_thunderbird_config(monkeypatch, tmp_path):
    monkeypatch.setattr(auth, "InstalledAppFlow", _FakeFlow)
    creds_file = tmp_path / "credentials.json"  # does NOT exist
    flow = auth._make_flow(creds_file, ["s"])
    assert flow["via"] == "client_config"
    assert flow["config"]["installed"]["client_id"] == thunderbird_client.THUNDERBIRD_GOOGLE_CLIENT_ID


def test_make_flow_credentials_file_overrides_when_present(monkeypatch, tmp_path):
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

    class _C:
        token = "t"
        refresh_token = "r"
        token_uri = "u"
        client_id = "c"
        client_secret = "s"
        scopes = ["https://mail.google.com/"]
        expiry = exp

    auth._save_token(tok, _C())
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
    monkeypatch.setattr(auth, "Request", lambda: object())
    return calls


def test_get_credentials_refreshes_when_expired(tmp_path, monkeypatch):
    tok = tmp_path / "token.json"
    _write_token(tok, expiry_iso=(datetime.now() - timedelta(hours=2)).isoformat())
    calls = _patch_refresh(monkeypatch)
    creds = auth.get_credentials(tok, tmp_path / "credentials.json", ["https://mail.google.com/"])
    assert calls["n"] == 1
    assert creds.token == "fresh-access"
    # the refreshed token (with new expiry) is written back
    assert _json.loads(tok.read_text())["token"] == "fresh-access"


def test_get_credentials_refreshes_when_expiry_unknown(tmp_path, monkeypatch):
    # a token saved by the OLD code path: no expiry field at all.
    tok = tmp_path / "token.json"
    _write_token(tok, expiry_iso=None)
    calls = _patch_refresh(monkeypatch)
    creds = auth.get_credentials(tok, tmp_path / "credentials.json", ["https://mail.google.com/"])
    assert calls["n"] == 1
    assert creds.token == "fresh-access"
