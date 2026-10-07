import json

import msal
from email_client import browser_reauth as br
from email_client import imap


class _FailingApp:
    def __init__(self, *a, **k):
        pass

    def acquire_token_by_refresh_token(self, rt, scopes):
        return {"error": "invalid_grant", "error_codes": [50078]}


def _setup(tmp_path, monkeypatch, session="s"):
    monkeypatch.setattr(br, "NOTIF_DIR", tmp_path / "notifs")
    monkeypatch.setattr(imap, "account_dir", lambda a: tmp_path)
    monkeypatch.setattr(imap, "load_config", lambda a: {"browser_session": session} if session else {})
    monkeypatch.setattr(imap, "account_user", lambda a: "u@example.org")
    monkeypatch.setattr(msal, "PublicClientApplication", _FailingApp)


PROFILE = {"oauth_client_id": "c", "oauth_authority": "a", "oauth_scopes": []}


def test_mfa_expiry_recovers_via_browser_once_then_cools_down(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(br, "silent_reauth", lambda p, u, s: calls.append(s) or {"access_token": "new", "expires_in": 3600})
    res = imap._refresh_microsoft({"refresh_token": "r"}, PROFILE, "acct")
    assert res["access_token"] == "new"
    assert calls == ["s"]
    notifs = list((tmp_path / "notifs").glob("*browser_reauth*"))
    assert len(notifs) == 1 and json.loads(notifs[0].read_text())["ok"] is True
    # A second failure inside the cooldown does not open the browser again.
    try:
        imap._refresh_microsoft({"refresh_token": "r"}, PROFILE, "acct")
    except SystemExit as e:
        assert "refresh failed" in str(e)
    assert calls == ["s"]


def test_no_browser_session_configured_keeps_old_failure(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, session=None)
    monkeypatch.setattr(br, "silent_reauth", lambda *a: (_ for _ in ()).throw(AssertionError("must not run")))
    try:
        imap._refresh_microsoft({"refresh_token": "r"}, PROFILE, "acct")
    except SystemExit as e:
        assert "refresh failed" in str(e)


def test_needs_mfa_refresh_only_for_interaction_errors():
    assert br.needs_mfa_refresh({"error_codes": [50078]})
    assert br.needs_mfa_refresh({"error": "interaction_required"})
    assert not br.needs_mfa_refresh({"error": "invalid_client", "error_codes": [7000215]})
