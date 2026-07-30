"""Tests for the Google OAuth client health-probe + self-heal (Parts 2 & 3).

The core requirement: the classifier must distinguish a DEAD CLIENT
(deleted_client / invalid_client-not-found) from a BAD USER TOKEN (invalid_grant)
from a HEALTHY refresh. We mock the token-endpoint responses for each class; no
network, and the imap account layer is monkeypatched per test.
"""

import json

import pytest
from email_client import google_health as gh

DEAD_ID = "dead-000.apps.googleusercontent.com"
NEW_ID = "fresh-999.apps.googleusercontent.com"

# Canonical token-endpoint responses for each error class (status, body).
RESP_DELETED_CLIENT = (401, {"error": "deleted_client", "error_description": "The OAuth client was deleted."})
RESP_INVALID_CLIENT = (401, {"error": "invalid_client", "error_description": "The OAuth client was not found."})
RESP_INVALID_GRANT = (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
# A LIVE client presented with the wrong secret: same error code, different meaning.
RESP_BAD_CLIENT_SECRET = (401, {"error": "invalid_client", "error_description": "The provided client secret is invalid."})
RESP_SUCCESS = (200, {"access_token": "ya29.new", "expires_in": 3599})


# -- classifier -----------------------------------------------------


def test_classify_deleted_client_is_dead():
    assert gh.classify_refresh_response(*RESP_DELETED_CLIENT) == gh.DEAD_CLIENT


def test_classify_invalid_client_not_found_is_dead():
    assert gh.classify_refresh_response(*RESP_INVALID_CLIENT) == gh.DEAD_CLIENT


def test_classify_invalid_client_bad_secret_is_stale_secret_not_dead():
    # Google answers 401 invalid_client when a LIVE client is sent a wrong secret.
    # Calling that client dead would notify the user their client was removed.
    result = gh.classify_refresh_response(*RESP_BAD_CLIENT_SECRET)
    assert result == gh.STALE_CLIENT_SECRET
    assert result != gh.DEAD_CLIENT
    # It is still a client-side fault, so it must stay on the self-heal path.
    assert result in gh.CLIENT_FAULT_STATUSES


def test_classify_invalid_client_bad_secret_matching_is_case_insensitive():
    resp = (401, {"error": "INVALID_CLIENT", "error_description": "The Provided Client Secret Is Invalid."})
    assert gh.classify_refresh_response(*resp) == gh.STALE_CLIENT_SECRET


def test_classify_invalid_client_deleted_wins_over_secret_wording():
    # If the description says the client is gone, it is dead even if it also
    # mentions the secret.
    resp = (401, {"error": "invalid_client", "error_description": "The OAuth client secret was not found."})
    assert gh.classify_refresh_response(*resp) == gh.DEAD_CLIENT


def test_classify_invalid_client_without_description_stays_dead():
    assert gh.classify_refresh_response(401, {"error": "invalid_client"}) == gh.DEAD_CLIENT


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
    classification, status, _body = gh.probe_refresh("cid", "secret", "RT", post=post)
    assert classification == gh.BAD_TOKEN
    assert status == 400
    assert seen["params"]["grant_type"] == "refresh_token"
    assert seen["params"]["refresh_token"] == "RT"
    assert seen["params"]["client_id"] == "cid"


# -- account-level probe + self-heal (imap account layer monkeypatched) ----------


def _install_fake_imap_client(monkeypatch, token, provider="gmail", client_id=DEAD_ID, accounts=("personal",)):
    from email_client import imap

    strategy = "loopback-oauth" if provider == "gmail" else "app-password"
    profile = {
        "auth_strategy": strategy,
        "oauth_client_id": client_id,
        "oauth_client_secret": "sek",
        "oauth_token_url": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setattr(imap, "load_token", lambda acc: token)
    monkeypatch.setattr(imap, "account_profile", lambda acc: (provider, dict(profile)))
    monkeypatch.setattr(imap, "list_accounts", lambda: list(accounts))


def _post_by_client(mapping):
    def post(token_url, params):
        return mapping[params["client_id"]]

    return post


def _post_by_creds(mapping):
    """Response keyed on ``(client_id, client_secret)``, for secret-rotation cases."""

    def post(token_url, params):
        return mapping[(params["client_id"], params.get("client_secret"))]

    return post


@pytest.fixture(autouse=True)
def _isolate_notifs(tmp_path, monkeypatch):
    monkeypatch.setattr(gh, "NOTIF_DIR", tmp_path / "notifications")


def test_probe_account_skips_non_google(monkeypatch):
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, provider="yahoo-app-password")
    res = gh.probe_account("personal")
    assert res["status"] == gh.SKIPPED
    assert "not a Google" in res["reason"]


def test_probe_account_skips_when_no_stored_token(monkeypatch):
    _install_fake_imap_client(monkeypatch, None)
    res = gh.probe_account("personal")
    assert res["status"] == gh.SKIPPED
    assert "no stored refresh token" in res["reason"]


def test_probe_account_healthy(monkeypatch):
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"})
    res = gh.probe_account("personal", post=_post_by_client({DEAD_ID: RESP_SUCCESS}))
    assert res["status"] == gh.HEALTHY


def test_probe_account_bad_token_does_not_notify_or_heal(monkeypatch, tmp_path):
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"})
    # invalid_grant -> bad token; run_probe must NOT self-heal or notify.
    called = {"heal": False}
    monkeypatch.setattr(gh, "attempt_self_heal", lambda *a, **k: called.__setitem__("heal", True))
    res = gh.run_probe("personal", post=_post_by_client({DEAD_ID: RESP_INVALID_GRANT}))
    assert res["status"] == gh.BAD_TOKEN
    assert called["heal"] is False
    assert not (gh.NOTIF_DIR).exists() or list(gh.NOTIF_DIR.glob("*.json")) == []


def test_run_probe_bad_client_secret_reresolves_but_does_not_notify(monkeypatch):
    # A stale secret on a still-live client id must keep the recovery path (the
    # client re-resolve) and lose only the "client was removed upstream" notice.
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    called = {"heal": 0}

    def _fake_heal(*a, **k):
        called["heal"] += 1
        return {"status": gh.STALE_CLIENT_SECRET, "healed": False}

    monkeypatch.setattr(gh, "attempt_self_heal", _fake_heal)
    res = gh.run_probe("personal", post=_post_by_client({DEAD_ID: RESP_BAD_CLIENT_SECRET}))
    assert res["status"] == gh.STALE_CLIENT_SECRET
    assert called["heal"] == 1
    assert "notification" not in res
    assert not gh.NOTIF_DIR.exists() or list(gh.NOTIF_DIR.glob("*.json")) == []


def test_run_probe_heals_rotated_client_secret_on_same_client_id(monkeypatch):
    # Upstream rotated the shipped secret but kept the client id: the re-resolve
    # picks up the new secret and the retry succeeds, silently.
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    post = _post_by_creds({(DEAD_ID, "sek"): RESP_BAD_CLIENT_SECRET, (DEAD_ID, "rotated"): RESP_SUCCESS})
    monkeypatch.setattr(
        "email_client.thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": DEAD_ID, "client_secret": "rotated", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post)
    assert res["status"] == gh.HEALED
    assert res["self_heal"]["healed"] is True
    assert not gh.NOTIF_DIR.exists() or list(gh.NOTIF_DIR.glob("*.json")) == []


def test_run_probe_stale_secret_unhealed_still_does_not_notify(monkeypatch):
    # Upstream had nothing better to give, so the retry fails too. Still no
    # notification: the client id is alive, it was never removed upstream.
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    monkeypatch.setattr(
        "email_client.thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": DEAD_ID, "client_secret": "sek", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=_post_by_client({DEAD_ID: RESP_BAD_CLIENT_SECRET}))
    assert res["status"] == gh.STALE_CLIENT_SECRET
    assert res["self_heal"]["healed"] is False
    assert not gh.NOTIF_DIR.exists() or list(gh.NOTIF_DIR.glob("*.json")) == []


def test_self_heal_gives_up_when_nothing_fresh_was_fetched(monkeypatch):
    # Same client id AND no upstream fetch (cache/fallback): there is nothing new
    # to try, so do not spend a second token call on credentials known to fail.
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    calls = {"n": 0}

    def _post(_url, _params):
        calls["n"] += 1
        return RESP_DELETED_CLIENT

    monkeypatch.setattr(
        "email_client.thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": DEAD_ID, "client_secret": "sek", "source": "cache-stale"},
    )
    heal = gh.attempt_self_heal("personal", {"client_id": DEAD_ID}, post=_post)
    assert heal["healed"] is False
    assert calls["n"] == 0


def test_run_probe_deleted_client_reresolves_and_notifies(monkeypatch):
    # The other direction: a genuinely deleted client keeps BOTH the re-resolve
    # and the notification.
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    called = {"heal": 0}

    def _fake_heal(*a, **k):
        called["heal"] += 1
        return {"status": gh.DEAD_CLIENT, "healed": False}

    monkeypatch.setattr(gh, "attempt_self_heal", _fake_heal)
    res = gh.run_probe("personal", post=_post_by_client({DEAD_ID: RESP_DELETED_CLIENT}))
    assert res["status"] == gh.DEAD_CLIENT
    assert called["heal"] == 1
    assert res["notification"]
    assert len(list(gh.NOTIF_DIR.glob("*.json"))) == 1


def test_run_probe_self_heals_with_fresh_client(monkeypatch):
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    # Dead client on DEAD_ID, but the freshly-resolved client NEW_ID works.
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_SUCCESS})
    monkeypatch.setattr(
        "email_client.thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": NEW_ID, "client_secret": "s2", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post)
    assert res["status"] == gh.HEALED
    assert res["self_heal"]["healed"] is True
    assert res["self_heal"]["client_id"] == NEW_ID
    # Healed -> no notification.
    assert not gh.NOTIF_DIR.exists() or list(gh.NOTIF_DIR.glob("*.json")) == []


def test_run_probe_notifies_when_fresh_client_identical(monkeypatch):
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT})
    # Upstream has not fixed it: the fresh client is the same dead id.
    monkeypatch.setattr(
        "email_client.thunderbird_client.resolve_google_client",
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
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_INVALID_CLIENT})
    monkeypatch.setattr(
        "email_client.thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": NEW_ID, "client_secret": "s2", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post)
    assert res["status"] == gh.DEAD_CLIENT
    assert res["self_heal"]["healed"] is False
    assert len(list(gh.NOTIF_DIR.glob("*.json"))) == 1


def test_run_probe_no_notify_flag(monkeypatch):
    _install_fake_imap_client(monkeypatch, {"refresh_token": "RT"}, client_id=DEAD_ID)
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT})
    monkeypatch.setattr(
        "email_client.thunderbird_client.resolve_google_client",
        lambda *a, **k: {"client_id": DEAD_ID, "client_secret": "sek", "source": "fetched"},
    )
    res = gh.run_probe("personal", post=post, notify=False)
    assert res["status"] == gh.DEAD_CLIENT
    assert not gh.NOTIF_DIR.exists() or list(gh.NOTIF_DIR.glob("*.json")) == []
