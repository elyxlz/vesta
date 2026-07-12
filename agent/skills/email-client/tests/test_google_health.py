"""Tests for the Google OAuth client health-probe + self-heal (Parts 2 & 3).

The core requirement: the classifier must distinguish a DEAD CLIENT
(deleted_client / invalid_client-not-found) from a BAD USER TOKEN (invalid_grant)
from a HEALTHY refresh. We mock the token-endpoint responses for each class; no
network and no runtime venv (imap_client is stubbed in sys.modules).
"""

import json
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import google_health as gh  # noqa: E402

DEAD_ID = "dead-000.apps.googleusercontent.com"
NEW_ID = "fresh-999.apps.googleusercontent.com"

# Canonical token-endpoint responses for each error class (status, body).
RESP_DELETED_CLIENT = (401, {"error": "deleted_client", "error_description": "The OAuth client was deleted."})
RESP_INVALID_CLIENT = (401, {"error": "invalid_client", "error_description": "The OAuth client was not found."})
RESP_INVALID_GRANT = (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
RESP_SUCCESS = (200, {"access_token": "ya29.new", "expires_in": 3599})


# -- classifier -----------------------------------------------------


def test_classify_deleted_client_is_dead():
    assert gh.classify_refresh_response(*RESP_DELETED_CLIENT) == gh.DEAD_CLIENT


def test_classify_invalid_client_not_found_is_dead():
    assert gh.classify_refresh_response(*RESP_INVALID_CLIENT) == gh.DEAD_CLIENT


def test_classify_invalid_grant_is_bad_token_not_dead():
    result = gh.classify_refresh_response(*RESP_INVALID_GRANT)
    assert result == gh.BAD_TOKEN
    assert result != gh.DEAD_CLIENT


def test_classify_success_is_healthy():
    assert gh.classify_refresh_response(*RESP_SUCCESS) == gh.HEALTHY


def test_classify_generic_not_found_description_is_dead():
    resp = (400, {"error": "invalid_request", "error_description": "OAuth client was not found"})
    assert gh.classify_refresh_response(*resp) == gh.DEAD_CLIENT


def test_classify_unknown_error_is_not_dead():
    # A transient/unexpected error must NOT be treated as a dead client.
    resp = (500, {"error": "internal_failure"})
    assert gh.classify_refresh_response(*resp) == gh.UNKNOWN


# -- probe_refresh wiring -------------------------------------------


def _post_returning(response):
    seen = {}

    def post(token_url, params):
        seen["params"] = params
        return response

    return post, seen


def test_probe_refresh_sends_refresh_grant_and_classifies():
    post, seen = _post_returning(RESP_INVALID_GRANT)
    classification, status, body = gh.probe_refresh("cid", "secret", "RT", post=post)
    assert classification == gh.BAD_TOKEN
    assert status == 400
    assert seen["params"]["grant_type"] == "refresh_token"
    assert seen["params"]["refresh_token"] == "RT"
    assert seen["params"]["client_id"] == "cid"


# -- account-level probe + self-heal (imap_client stubbed) ----------


def _install_fake_imap_client(token, provider="gmail", client_id=DEAD_ID, accounts=("personal",)):
    ic = types.ModuleType("imap_client")
    strategy = "loopback-oauth" if provider == "gmail" else "app-password"
    profile = {
        "auth_strategy": strategy,
        "oauth_client_id": client_id,
        "oauth_client_secret": "sek",
        "oauth_token_url": "https://oauth2.googleapis.com/token",
    }
    ic.load_token = lambda acc: token
    ic.account_profile = lambda acc: (provider, dict(profile))
    ic.list_accounts = lambda: list(accounts)
    sys.modules["imap_client"] = ic
    return ic


def _post_by_client(mapping):
    def post(token_url, params):
        return mapping[params["client_id"]]

    return post


@pytest.fixture(autouse=True)
def _isolate_notifs(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "NOTIF_DIR", tmp_path / "notifications")
    yield
    sys.modules.pop("imap_client", None)


def test_probe_account_skips_non_google():
    _install_fake_imap_client({"refresh_token": "RT"}, provider="yahoo-app-password")
    res = gh.probe_account("personal")
    assert res["status"] == gh.SKIPPED
    assert "not a Google" in res["reason"]


def test_probe_account_skips_when_no_stored_token():
    _install_fake_imap_client(None)
    res = gh.probe_account("personal")
    assert res["status"] == gh.SKIPPED
    assert "no stored refresh token" in res["reason"]


def test_probe_account_healthy():
    _install_fake_imap_client({"refresh_token": "RT"})
    res = gh.probe_account("personal", post=_post_by_client({DEAD_ID: RESP_SUCCESS}))
    assert res["status"] == gh.HEALTHY


def test_probe_account_bad_token_does_not_notify_or_heal(monkeypatch, tmp_path):
    _install_fake_imap_client({"refresh_token": "RT"})
    # invalid_grant -> bad token; run_probe must NOT self-heal or notify.
    called = {"heal": False}
    monkeypatch.setattr(gh, "attempt_self_heal", lambda *a, **k: called.__setitem__("heal", True))
    res = gh.run_probe("personal", post=_post_by_client({DEAD_ID: RESP_INVALID_GRANT}))
    assert res["status"] == gh.BAD_TOKEN
    assert called["heal"] is False
    assert not (gh.NOTIF_DIR).exists() or list(gh.NOTIF_DIR.glob("*.json")) == []


def test_run_probe_self_heals_with_fresh_client(monkeypatch):
    _install_fake_imap_client({"refresh_token": "RT"}, client_id=DEAD_ID)
    # Dead client on DEAD_ID, but the freshly-resolved client NEW_ID works.
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_SUCCESS})
    monkeypatch.setattr(
        "thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": NEW_ID, "client_secret": "s2", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post)
    assert res["status"] == gh.HEALED
    assert res["self_heal"]["healed"] is True
    assert res["self_heal"]["client_id"] == NEW_ID
    # Healed -> no notification.
    assert not gh.NOTIF_DIR.exists() or list(gh.NOTIF_DIR.glob("*.json")) == []


def test_run_probe_notifies_when_fresh_client_identical(monkeypatch):
    _install_fake_imap_client({"refresh_token": "RT"}, client_id=DEAD_ID)
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT})
    # Upstream has not fixed it: the fresh client is the same dead id.
    monkeypatch.setattr(
        "thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": DEAD_ID, "client_secret": "sek", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post)
    assert res["status"] == gh.DEAD_CLIENT
    assert res["self_heal"]["healed"] is False
    files = list(gh.NOTIF_DIR.glob("*.json"))
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["interrupt"] is True
    assert notif["type"] == "google_client_dead"
    assert "Gmail stopped working" in notif["message"]


def test_run_probe_notifies_when_fresh_client_also_dead(monkeypatch):
    _install_fake_imap_client({"refresh_token": "RT"}, client_id=DEAD_ID)
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_INVALID_CLIENT})
    monkeypatch.setattr(
        "thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": NEW_ID, "client_secret": "s2", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post)
    assert res["status"] == gh.DEAD_CLIENT
    assert res["self_heal"]["healed"] is False
    assert len(list(gh.NOTIF_DIR.glob("*.json"))) == 1


def test_run_probe_no_notify_flag(monkeypatch):
    _install_fake_imap_client({"refresh_token": "RT"}, client_id=DEAD_ID)
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT})
    monkeypatch.setattr(
        "thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": DEAD_ID, "client_secret": "sek", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post, notify=False)
    assert res["status"] == gh.DEAD_CLIENT
    assert not gh.NOTIF_DIR.exists() or list(gh.NOTIF_DIR.glob("*.json")) == []
