"""Tests for the onboard CLI — the conduit flow with a mocked client + temp state."""

from __future__ import annotations

import json

import pytest

from onboard_cli import cli as cli_mod
from onboard_cli import state as state_mod
from onboard_cli.client import OnboardError

E = "ada@example.com"


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    """Point the session store at a throwaway dir so tests don't touch ~/.config."""
    monkeypatch.setattr(state_mod, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "_STATE_FILE", tmp_path / "sessions.json")


def _run(argv, capsys):
    rc = cli_mod.main(argv)
    out = capsys.readouterr().out
    return rc, (json.loads(out) if out.strip() else None)


def _verified(token="TOK"):
    """Seed a verified session for E."""
    state_mod.update(E, token=token)


def _active_server(monkeypatch, status="active"):
    monkeypatch.setattr(
        cli_mod.Client,
        "me",
        lambda self, t: {
            "user": {"id": "u1", "email": E},
            "server": {"id": "srv1", "subdomain": "ada", "status": status, "url": "https://ada.vesta.run"},
        },
    )
    monkeypatch.setattr(cli_mod.Client, "server_token", lambda self, t, sid: "VTOK")


# --- reference data ---------------------------------------------------------


def test_links(capsys):
    rc, data = _run(["links"], capsys)
    assert rc == 0 and data["marketing"] == "https://vesta.run"


def test_presets_has_models_and_floors(capsys):
    rc, data = _run(["presets"], capsys)
    assert rc == 0
    assert "dry" in data["personalities"]
    assert data["plan_floor_usd"] == {"starter": 12, "pro": 24, "power": 48}
    assert data["claude_models"] == ["opus", "sonnet", "haiku"]


# --- verify -----------------------------------------------------------------


def test_verify_stores_session(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "send_otp", lambda self, email: {"success": True})
    monkeypatch.setattr(cli_mod.Client, "verify_otp", lambda self, email, code: "SESS")
    assert _run(["verify-send", "--email", E], capsys)[0] == 0
    rc, data = _run(["verify", "--email", E, "--code", "123456"], capsys)
    assert rc == 0 and data["verified"] is True
    assert state_mod.token_for(E) == "SESS"


def test_verify_rejects_bad_code(capsys, monkeypatch):
    # A wrong/expired code -> verify_otp returns None -> surfaced as exit 2, not a
    # transport failure (exit 3), and no session is stored.
    monkeypatch.setattr(cli_mod.Client, "verify_otp", lambda self, email, code: None)
    rc, data = _run(["verify", "--email", E, "--code", "000000"], capsys)
    assert rc == 2 and "wrong or expired" in data["error"]
    assert state_mod.token_for(E) is None


# --- checkout ---------------------------------------------------------------


def test_checkout_requires_verification(capsys):
    rc, data = _run(["checkout", "--email", E], capsys)
    assert rc == 2 and "not verified" in data["error"]


def test_checkout_forwards_price_code_referral(capsys, monkeypatch):
    _verified()
    captured = {}

    def fake_checkout(self, *, token, plan, referral_code, price, code):
        captured.update(token=token, plan=plan, referral_code=referral_code, price=price, code=code)
        return {"url": "https://checkout.stripe.com/x", "subdomain": "ada"}

    monkeypatch.setattr(cli_mod.Client, "checkout", fake_checkout)
    monkeypatch.setattr(cli_mod.Client, "me", lambda self, t: {"server": {"id": "srv1"}})
    rc, data = _run(
        ["checkout", "--email", E, "--price", "200", "--code", " friend50 ", "--referral", "ref_x"],
        capsys,
    )
    assert rc == 0 and data["url"].startswith("https://checkout.stripe.com/")
    assert captured == {"token": "TOK", "plan": "pro", "referral_code": "ref_x", "price": 200.0, "code": "friend50"}
    assert state_mod.load(E)["server_id"] == "srv1"


def test_checkout_rejects_below_floor_without_calling(capsys, monkeypatch):
    _verified()
    calls = {"n": 0}
    monkeypatch.setattr(cli_mod.Client, "checkout", lambda self, **kw: calls.__setitem__("n", calls["n"] + 1) or {"url": "x"})
    rc, data = _run(["checkout", "--email", E, "--price", "5"], capsys)
    assert rc == 2 and data["floor_usd"] == 24 and calls["n"] == 0


def test_checkout_surfaces_structured_error(capsys, monkeypatch):
    _verified()
    monkeypatch.setattr(cli_mod.Client, "checkout", lambda self, **kw: {"error": "already provisioned"})
    rc, data = _run(["checkout", "--email", E], capsys)
    assert rc == 2 and data["error"] == "already provisioned"


# --- status -----------------------------------------------------------------


def test_status_reports_server_state(capsys, monkeypatch):
    _verified()
    _active_server(monkeypatch)
    rc, data = _run(["status", "--email", E], capsys)
    assert rc == 0 and data["status"] == "active" and data["url"] == "https://ada.vesta.run"


# --- create-agent -----------------------------------------------------------


def test_create_agent_needs_active_server(capsys, monkeypatch):
    _verified()
    _active_server(monkeypatch, status="reserved")
    rc, data = _run(["create-agent", "--email", E, "--name", "Ada"], capsys)
    assert rc == 2 and "not ready" in data["error"]


def test_create_agent_passes_seed(capsys, monkeypatch):
    _verified()
    _active_server(monkeypatch)
    captured = {}

    def fake_create(self, *, subdomain, server_token, name, personality, skills):
        captured.update(subdomain=subdomain, server_token=server_token, name=name, personality=personality, skills=skills)
        # vestad normalizes the name and returns the actual created name.
        return {"name": "ada"}

    monkeypatch.setattr(cli_mod.Client, "create_agent", fake_create)
    rc, data = _run(
        ["create-agent", "--email", E, "--name", "Ada", "--personality", "Dry", "--skills", "email, calendar ,"],
        capsys,
    )
    assert rc == 0 and data["created"] is True and data["name"] == "ada"
    assert captured["subdomain"] == "ada" and captured["server_token"] == "VTOK"
    assert captured["personality"] == "dry" and captured["skills"] == ["email", "calendar"]
    # the NORMALIZED name vestad returned is stored, so claude-finish addresses a
    # path vestad's validate_name accepts (not the raw "Ada").
    assert state_mod.load(E)["agent_name"] == "ada"


# --- claude connect ---------------------------------------------------------


def test_claude_start_stores_session(capsys, monkeypatch):
    _verified()
    _active_server(monkeypatch)
    monkeypatch.setattr(
        cli_mod.Client,
        "claude_oauth_start",
        lambda self, *, subdomain, server_token: {"auth_url": "https://claude.ai/oauth", "session_id": "CS"},
    )
    rc, data = _run(["claude-start", "--email", E], capsys)
    assert rc == 0 and data["auth_url"] == "https://claude.ai/oauth"
    assert state_mod.load(E)["claude_session_id"] == "CS"


def test_claude_finish_connects_and_clears(capsys, monkeypatch):
    _verified()
    state_mod.update(E, claude_session_id="CS", agent_name="Ada")
    _active_server(monkeypatch)
    monkeypatch.setattr(
        cli_mod.Client,
        "claude_oauth_complete",
        lambda self, *, subdomain, server_token, session_id, code: (
            "CREDS" if (session_id == "CS" and code == "PASTE") else pytest.fail("bad relay")
        ),
    )
    captured = {}

    def fake_set(self, *, subdomain, server_token, name, credentials, model):
        captured.update(name=name, credentials=credentials, model=model)
        return {"ok": True}

    monkeypatch.setattr(cli_mod.Client, "set_provider", fake_set)
    rc, data = _run(["claude-finish", "--email", E, "--code", "PASTE"], capsys)
    assert rc == 0 and data["connected"] is True and data["name"] == "Ada"
    assert captured == {"name": "Ada", "credentials": "CREDS", "model": "sonnet"}
    # onboarding complete -> session forgotten
    assert state_mod.token_for(E) is None


def test_claude_finish_without_start(capsys, monkeypatch):
    _verified()
    _active_server(monkeypatch)
    rc, data = _run(["claude-finish", "--email", E, "--code", "PASTE"], capsys)
    assert rc == 2 and "claude-start" in data["error"]


def test_claude_finish_clears_session_when_attach_fails(capsys, monkeypatch):
    _verified()
    state_mod.update(E, claude_session_id="CS", agent_name="ada")
    _active_server(monkeypatch)
    monkeypatch.setattr(
        cli_mod.Client,
        "claude_oauth_complete",
        lambda self, *, subdomain, server_token, session_id, code: "CREDS",
    )
    # The attach (set_provider) fails after OAuth was consumed on the VM.
    monkeypatch.setattr(
        cli_mod.Client,
        "set_provider",
        lambda self, *, subdomain, server_token, name, credentials, model: {"error": "bad gateway"},
    )
    rc, data = _run(["claude-finish", "--email", E, "--code", "PASTE"], capsys)
    assert rc == 2 and "claude-start" in data["error"]
    # The consumed session_id is forgotten (a retry must re-run claude-start), but
    # the buyer's session token survives so they aren't kicked out mid-onboard.
    assert "claude_session_id" not in state_mod.load(E)
    assert state_mod.token_for(E) == "TOK"


# --- error propagation ------------------------------------------------------


def test_unreachable_control_plane_exits_3(capsys, monkeypatch):
    def boom(self, email):
        raise OnboardError("could not reach https://vesta.run/api")

    monkeypatch.setattr(cli_mod.Client, "send_otp", boom)
    rc, data = _run(["verify-send", "--email", E], capsys)
    assert rc == 3 and "could not reach" in data["error"]
