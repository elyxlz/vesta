"""Tests for the unified onboarding + silent-refresh surface.

The browser-driving itself (headed Xvfb, token extraction JS) is exercised live, not here; these
lock the logic around it: token persistence, refresh scheduling, the `auth setup` state machine, and
the friendly scope-error on a 403.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from microsoft_cli import auth_commands, backend, capture, cli, owa_rest, teams
from microsoft_cli.config import Config


def _http_error(status: int) -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me/chats")
    return httpx.HTTPStatusError("err", request=req, response=httpx.Response(status, request=req))


# ---------------------------------------------------------------------------
# Token-store expiry helpers
# ---------------------------------------------------------------------------


def test_browser_token_expiry_reads_browser_marker(tmp_path):
    cfg = Config(data_dir=tmp_path)
    exp = time.time() + 3600
    owa_rest.save_token("a@x.com", cfg, token="t", expires_at=exp)
    teams.save_token("a@x.com", cfg, token="t", expires_at=exp)
    assert owa_rest.browser_token_expiry("a@x.com", cfg) == pytest.approx(exp)
    assert teams.browser_token_expiry("a@x.com", cfg) == pytest.approx(exp)


def test_browser_token_expiry_none_for_device_or_missing(tmp_path):
    cfg = Config(data_dir=tmp_path)
    assert owa_rest.browser_token_expiry("nobody@x.com", cfg) is None
    teams.mark_device_account("dev@x.com", cfg)
    assert teams.browser_token_expiry("dev@x.com", cfg) is None


# ---------------------------------------------------------------------------
# capture: persistence + refresh scheduling
# ---------------------------------------------------------------------------


def test_save_captured_persists_both_tokens(tmp_path):
    cfg = Config(data_dir=tmp_path)
    future = time.time() + 7200
    saved = capture.save_captured(cfg, "a@x.com", {"mail": {"token": "m", "expires_at": future}, "teams": {"token": "t", "expires_at": future}})
    assert saved == ["mail/calendar", "Teams"]
    assert owa_rest.load_token("a@x.com", cfg) == "m"
    assert teams.captured_token(cfg, "a@x.com") == "t"


def test_save_captured_partial(tmp_path):
    cfg = Config(data_dir=tmp_path)
    saved = capture.save_captured(cfg, "a@x.com", {"mail": {"token": "m", "expires_at": time.time() + 7200}})
    assert saved == ["mail/calendar"]
    assert teams.has_token("a@x.com", cfg) is False


def test_due_accounts_flags_near_expiry_only(tmp_path):
    cfg = Config(data_dir=tmp_path)
    now = time.time()
    owa_rest.save_token("soon@x.com", cfg, token="m", expires_at=now + 600)  # within 2h margin
    owa_rest.save_token("later@x.com", cfg, token="m", expires_at=now + 6 * 3600)  # outside
    due = capture.due_accounts(cfg, now)
    assert due == ["soon@x.com"]


def test_due_accounts_ignores_device_accounts(tmp_path):
    cfg = Config(data_dir=tmp_path)
    teams.mark_device_account("dev@x.com", cfg)
    assert capture.due_accounts(cfg, time.time()) == []


def test_refresh_and_save_persists(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    future = time.time() + 7200
    monkeypatch.setattr(capture, "refresh", lambda config, acct: {"mail": {"token": "fresh", "expires_at": future}})
    saved = capture.refresh_and_save(cfg, "a@x.com")
    assert saved == ["mail/calendar"]
    assert owa_rest.load_token("a@x.com", cfg) == "fresh"


# ---------------------------------------------------------------------------
# auth setup state machine
# ---------------------------------------------------------------------------


def _fake_app(flow=None, result=None):
    app = MagicMock()
    app.initiate_device_flow.return_value = flow or {}
    app.acquire_token_by_device_flow.return_value = result or {}
    app.token_cache = MagicMock()  # not a SerializableTokenCache -> write skipped
    return app


def test_setup_start_personal_returns_device_code(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = _fake_app(flow={"user_code": "ABC123", "verification_uri": "https://ms/device", "expires_in": 900})
    monkeypatch.setattr(auth_commands.auth, "get_app", lambda *a, **k: app)
    out = auth_commands.auth_setup(cfg, account_email="a@outlook.com")
    assert out["status"] == "device_code"
    assert out["code"] == "ABC123"
    assert "_flow_cache" in out


def test_setup_start_work_domain_defaults_to_browser(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(auth_commands.capture, "begin_interactive", lambda config, acct: "http://localhost:6080/handover.html")
    out = auth_commands.auth_setup(cfg, account_email="a@somecompany.com")
    assert out["status"] == "sign_in"  # custom domain skips the device-code round-trip
    assert out["user_url"].endswith("handover.html")


def test_setup_work_domain_force_device_returns_device_code(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = _fake_app(flow={"user_code": "ABC123", "verification_uri": "https://ms/device", "expires_in": 900})
    monkeypatch.setattr(auth_commands.auth, "get_app", lambda *a, **k: app)
    out = auth_commands.auth_setup(cfg, account_email="a@somecompany.com", force_device=True)
    assert out["status"] == "device_code"
    assert out["code"] == "ABC123"


def test_setup_browser_flag_starts_handover(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    monkeypatch.setattr(auth_commands.capture, "begin_interactive", lambda config, acct: "http://localhost:6080/handover.html")
    out = auth_commands.auth_setup(cfg, account_email="a@x.com", use_browser=True)
    assert out["status"] == "sign_in"
    assert out["user_url"].endswith("handover.html")
    assert "--capture" in out["next"]


def test_setup_flow_complete_success_marks_teams(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = _fake_app(result={"access_token": "tok", "id_token_claims": {"preferred_username": "a@x.com"}})
    monkeypatch.setattr(auth_commands.auth, "get_app", lambda *a, **k: app)
    out = auth_commands.auth_setup(cfg, account_email="a@x.com", flow_cache=json.dumps({"device_code": "d"}))
    assert out["status"] == "success"
    assert out["backend"] == "graph"
    assert "a@x.com" in teams.list_accounts(cfg)  # device marker written so the daemon polls Teams


def test_setup_flow_admin_wall_pivots_to_browser(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    app = _fake_app(result={"error": "access_denied", "error_description": "AADSTS65001 admin consent required"})
    monkeypatch.setattr(auth_commands.auth, "get_app", lambda *a, **k: app)
    monkeypatch.setattr(auth_commands.capture, "begin_interactive", lambda config, acct: "http://localhost:6080/handover.html")
    out = auth_commands.auth_setup(cfg, account_email="a@x.com", flow_cache=json.dumps({"device_code": "d"}))
    assert out["status"] == "sign_in"  # pivoted, no separate ask


def test_setup_capture_saves_tokens(monkeypatch, tmp_path):
    cfg = Config(data_dir=tmp_path)
    future = time.time() + 7200
    monkeypatch.setattr(
        auth_commands.capture,
        "finish_interactive",
        lambda config, acct: {"mail": {"token": "m", "expires_at": future}, "teams": {"token": "t", "expires_at": future}},
    )
    out = auth_commands.auth_setup(cfg, account_email="a@x.com", do_capture=True)
    assert out["status"] == "success"
    assert "mail/calendar" in out["provisioned"] and "Teams" in out["provisioned"]
    assert owa_rest.has_valid_token("a@x.com", cfg) and teams.has_token("a@x.com", cfg)


# ---------------------------------------------------------------------------
# Friendly 403 on a scope-limited Teams token
# ---------------------------------------------------------------------------


def test_dispatch_teams_403_gives_reauth_hint(monkeypatch):
    args = SimpleNamespace(backend=backend.OWA_REST, account="a@x.com", command="presence")
    monkeypatch.setattr(cli.teams, "captured_token", lambda config, acct: "tok")

    def _raise(client, token):
        raise _http_error(403)

    monkeypatch.setattr(cli.teams, "get_presence", _raise)
    with pytest.raises(PermissionError, match="auth setup"):
        cli._dispatch_teams(args, Config(), MagicMock())
