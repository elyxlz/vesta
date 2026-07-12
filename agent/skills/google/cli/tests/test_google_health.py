"""Health probe classifier + automatic self-heal escalation ladder (Parts 4 & 5).

The classifier must separate a DEAD CLIENT (deleted_client / invalid_client /
"not found") from a BAD USER TOKEN (invalid_grant) from a HEALTHY refresh. The
ladder must produce: silent-swap (Level 1) vs agent-request (Level 2) vs
user-notify (Level 3) correctly. Everything is mocked — no network: the token
endpoint (`post`) and the comm-central resolver are injected/monkeypatched.
"""

import json

import pytest

from google_cli import google_health as gh
from google_cli.config import Config

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


def _post_by_client(mapping):
    def post(token_url, params):
        return mapping[params["client_id"]]

    return post


# -- fixtures: an isolated Config + stored token --------------------


@pytest.fixture
def config(tmp_path):
    return Config(data_dir=tmp_path, log_dir=tmp_path / "logs")


def _write_token(config, refresh_token="RT", client_id=DEAD_ID, secret="sek"):
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.token_file.write_text(
        json.dumps(
            {
                "token": "x",
                "refresh_token": refresh_token,
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_id": client_id,
                "client_secret": secret,
                "scopes": [],
            }
        )
    )


def _notifs(notif_dir):
    return sorted(notif_dir.glob("*.json"))


# -- probe_config ---------------------------------------------------


def test_probe_config_skips_when_no_token(config):
    res = gh.probe_config(config)
    assert res["status"] == gh.SKIPPED


def test_probe_config_healthy(config):
    _write_token(config)
    res = gh.probe_config(config, post=_post_by_client({DEAD_ID: RESP_SUCCESS}))
    assert res["status"] == gh.HEALTHY
    assert res["client_id"] == DEAD_ID


def test_probe_config_bad_token(config):
    _write_token(config)
    res = gh.probe_config(config, post=_post_by_client({DEAD_ID: RESP_INVALID_GRANT}))
    assert res["status"] == gh.BAD_TOKEN


def test_probe_config_dead_client(config):
    _write_token(config)
    res = gh.probe_config(config, post=_post_by_client({DEAD_ID: RESP_DELETED_CLIENT}))
    assert res["status"] == gh.DEAD_CLIENT


# -- escalation ladder ----------------------------------------------


def _mock_resolver(monkeypatch, new_id, new_secret="s2", source="fetched"):
    monkeypatch.setattr(
        gh,
        "resolve_google_client",
        lambda *a, **k: {"client_id": new_id, "client_secret": new_secret, "source": source},
    )


def test_level1_silent_swap_heals_without_notification(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    # DEAD_ID dead, freshly-resolved NEW_ID works.
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_SUCCESS})
    _mock_resolver(monkeypatch, NEW_ID)

    res = gh.run_self_heal_cycle(config, notif_dir, post=post)

    assert res["status"] == gh.HEALED
    assert res["escalation"] == "silent_swap"
    assert res["self_heal"]["healed"] is True
    # Level 1 is SILENT: no notification of any kind.
    assert not notif_dir.exists() or _notifs(notif_dir) == []
    # The swap is durable: token.json now carries the fresh client.
    stored = json.loads(config.token_file.read_text())
    assert stored["client_id"] == NEW_ID
    # No escalation markers left behind.
    assert not gh._heal_request_marker(config).exists()


def test_level2_agent_request_when_fresh_client_also_dead(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_INVALID_CLIENT})
    _mock_resolver(monkeypatch, NEW_ID)

    res = gh.run_self_heal_cycle(config, notif_dir, post=post)

    assert res["status"] == gh.DEAD_CLIENT
    assert res["escalation"] == "agent_request"
    files = _notifs(notif_dir)
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["type"] == "google_client_heal_request"
    assert notif["interrupt"] is True
    assert "ACTION NEEDED (agent)" in notif["message"]
    assert notif["detail"]["dead_client_id"] == DEAD_ID
    # Marker written so the agent request is not repeated next cycle.
    assert gh._heal_request_marker(config).exists()
    # User has NOT been bothered.
    assert not gh._user_notified_marker(config).exists()


def test_level2_agent_request_when_fresh_client_identical(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT})
    # Upstream has not fixed it: fresh client == dead id.
    _mock_resolver(monkeypatch, DEAD_ID, new_secret="sek")

    res = gh.run_self_heal_cycle(config, notif_dir, post=post)

    assert res["status"] == gh.DEAD_CLIENT
    assert res["escalation"] == "agent_request"
    assert res["self_heal"]["healed"] is False
    files = _notifs(notif_dir)
    assert len(files) == 1
    assert json.loads(files[0].read_text())["type"] == "google_client_heal_request"


def test_level3_user_notify_when_marker_exists_and_still_dead(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_INVALID_CLIENT})
    _mock_resolver(monkeypatch, NEW_ID)
    # A heal-request marker already exists from a previous cycle.
    config.data_dir.mkdir(parents=True, exist_ok=True)
    gh._heal_request_marker(config).write_text("123.0")

    res = gh.run_self_heal_cycle(config, notif_dir, post=post)

    assert res["status"] == gh.DEAD_CLIENT
    assert res["escalation"] == "user_notify"
    files = _notifs(notif_dir)
    assert len(files) == 1
    notif = json.loads(files[0].read_text())
    assert notif["type"] == "google_client_dead"
    assert notif["interrupt"] is True
    assert "stopped working" in notif["message"]
    assert gh._user_notified_marker(config).exists()


def test_level3_stays_quiet_after_user_already_notified(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_INVALID_CLIENT})
    _mock_resolver(monkeypatch, NEW_ID)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    gh._heal_request_marker(config).write_text("123.0")
    gh._user_notified_marker(config).write_text("124.0")

    res = gh.run_self_heal_cycle(config, notif_dir, post=post)

    assert res["escalation"] == "already_user_notified"
    # No new notification written.
    assert not notif_dir.exists() or _notifs(notif_dir) == []


def test_bad_token_never_heals_or_notifies(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    called = {"heal": False}
    monkeypatch.setattr(gh, "attempt_self_heal", lambda *a, **k: called.__setitem__("heal", True) or {})
    post = _post_by_client({DEAD_ID: RESP_INVALID_GRANT})

    res = gh.run_self_heal_cycle(config, notif_dir, post=post)

    assert res["status"] == gh.BAD_TOKEN
    assert called["heal"] is False
    assert not notif_dir.exists() or _notifs(notif_dir) == []


def test_healthy_probe_clears_stale_markers(config, tmp_path):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    config.data_dir.mkdir(parents=True, exist_ok=True)
    gh._heal_request_marker(config).write_text("1.0")
    gh._user_notified_marker(config).write_text("1.0")

    res = gh.run_self_heal_cycle(config, notif_dir, post=_post_by_client({DEAD_ID: RESP_SUCCESS}))

    assert res["status"] == gh.HEALTHY
    assert not gh._heal_request_marker(config).exists()
    assert not gh._user_notified_marker(config).exists()


# -- run_probe_once (auth probe CLI) --------------------------------


def test_run_probe_once_never_writes_notifications(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    post = _post_by_client({DEAD_ID: RESP_DELETED_CLIENT, NEW_ID: RESP_SUCCESS})
    _mock_resolver(monkeypatch, NEW_ID)
    res = gh.run_probe_once(config, post=post)
    assert res["status"] == gh.HEALED
    # No notif dir touched by the manual probe.
    assert not (tmp_path / "notifications").exists()


# -- daily gate -----------------------------------------------------


def test_maybe_run_daily_probe_is_due_first_time_then_not(config, tmp_path, monkeypatch):
    _write_token(config, client_id=DEAD_ID)
    notif_dir = tmp_path / "notifications"
    _mock_resolver(monkeypatch, NEW_ID)
    monkeypatch.setattr(gh, "run_self_heal_cycle", lambda *a, **k: {"status": gh.HEALTHY})

    first = gh.maybe_run_daily_probe(config, notif_dir, now=1000.0)
    assert first is not None
    # Second call within the day is skipped.
    second = gh.maybe_run_daily_probe(config, notif_dir, now=1000.0 + 3600)
    assert second is None
    # A day later it is due again.
    third = gh.maybe_run_daily_probe(config, notif_dir, now=1000.0 + gh.PROBE_INTERVAL_SECS + 1)
    assert third is not None
