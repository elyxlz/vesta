"""Tests for the onboard CLI — the conduit flow with a mocked client + temp state."""

from __future__ import annotations

import json

import pytest

from onboard_cli import cli as cli_mod
from onboard_cli import referral_store
from onboard_cli import state as state_mod
from onboard_cli.client import OnboardError

E = "ada@example.com"


@pytest.fixture(autouse=True)
def _tmp_state(tmp_path, monkeypatch):
    """Point the session store at a throwaway dir so tests don't touch ~/.config."""
    monkeypatch.setattr(state_mod, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(state_mod, "_STATE_FILE", tmp_path / "sessions.json")
    # Same for the shared referral file (written by the vesta-cloud-account skill): point it at
    # a throwaway path, absent by default, so tests never touch ~/.config.
    monkeypatch.setattr(referral_store, "PATH", tmp_path / "referral_code")


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


def test_presets_lists_live_reference_data(capsys, monkeypatch):
    # `onboard presets` now reads personalities / models / defaults from the box's vestad
    # instead of hardcoding them, so the command is a pure consumer of that one source.
    monkeypatch.setattr(cli_mod.Client, "fetch_personalities", lambda self: [{"name": "dry"}, {"name": "chill"}])
    monkeypatch.setattr(cli_mod.Client, "fetch_claude_models", lambda self: [{"id": "opus"}, {"id": "sonnet"}, {"id": "haiku"}])
    monkeypatch.setattr(cli_mod.Client, "fetch_agent_defaults", lambda self: {"personality": "dry", "model": "opus"})
    rc, data = _run(["presets"], capsys)
    assert rc == 0
    assert "dry" in data["personalities"]
    assert data["plan_floor_usd"] == 24
    assert "plans" not in data  # single plan — no tier list
    assert data["claude_models"] == ["opus", "sonnet", "haiku"]
    assert data["default_personality"] == "dry"
    assert data["default_model"] == "opus"


# --- verify -----------------------------------------------------------------


def _mock_precreate(monkeypatch, result=None):
    """Stub the public account pre-create that `verify-send` does first (issue #79)."""
    monkeypatch.setattr(
        cli_mod.Client,
        "create_account",
        lambda self, email, code=None: result if result is not None else {"ok": True, "email": email, "referral_code_applied": bool(code)},
    )


def test_verify_stores_session(capsys, monkeypatch):
    _mock_precreate(monkeypatch)
    monkeypatch.setattr(cli_mod.Client, "send_otp", lambda self, email: {"success": True})
    monkeypatch.setattr(cli_mod.Client, "verify_otp", lambda self, email, code: "SESS")
    assert _run(["verify-send", "--email", E], capsys)[0] == 0
    rc, data = _run(["verify", "--email", E, "--code", "123456"], capsys)
    assert rc == 0 and data["verified"] is True
    assert state_mod.token_for(E) == "SESS"


def test_verify_send_records_intent_then_sends(capsys, monkeypatch):
    calls: dict[str, object] = {}

    def _create(self, email, code=None):
        calls["create"] = (email, code)
        return {"ok": True, "email": email, "referral_code_applied": bool(code)}

    def _send(self, email):
        calls["send"] = email
        return {"success": True}

    monkeypatch.setattr(cli_mod.Client, "create_account", _create)
    monkeypatch.setattr(cli_mod.Client, "send_otp", _send)
    rc, data = _run(["verify-send", "--email", E], capsys)
    assert rc == 0 and data["sent"] is True
    # No referral code in the env here, so the intent is recorded with code=None,
    # and the OTP is only sent after the intent is recorded.
    assert calls["create"] == (E, None)
    assert calls["send"] == E


def test_verify_send_sends_referral_code_from_shared_file(capsys, monkeypatch):
    referral_store.PATH.write_text("abc123\n")
    calls: dict[str, object] = {}

    def _create(self, email, code=None):
        calls["code"] = code
        return {"ok": True, "email": email, "referral_code_applied": bool(code)}

    monkeypatch.setattr(cli_mod.Client, "create_account", _create)
    monkeypatch.setattr(cli_mod.Client, "send_otp", lambda self, email: {"success": True})
    rc, data = _run(["verify-send", "--email", E], capsys)
    assert rc == 0 and data["referral_code_applied"] is True
    assert calls["code"] == "abc123"


def test_verify_send_surfaces_precreate_error_without_sending(capsys, monkeypatch):
    _mock_precreate(monkeypatch, result={"error": "unauthenticated"})

    def _no_send(self, email):
        raise AssertionError("send_otp must not run when pre-create fails")

    monkeypatch.setattr(cli_mod.Client, "send_otp", _no_send)
    rc, data = _run(["verify-send", "--email", E], capsys)
    assert rc == 2 and data["error"] == "unauthenticated"


def test_verify_send_self_hosted_still_onboards(capsys, monkeypatch):
    # No server-identity gate anymore (issue #79): a box with no VESTAD_PORT /
    # AGENT_TOKEN can still onboard through the public endpoint. create_account +
    # send_otp both run and it exits 0.
    _mock_precreate(monkeypatch)
    monkeypatch.setattr(cli_mod.Client, "send_otp", lambda self, email: {"success": True})
    rc, data = _run(["verify-send", "--email", E], capsys)
    assert rc == 0 and data["sent"] is True


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


def test_checkout_forwards_price_and_code_no_referral(capsys, monkeypatch):
    _verified()
    captured = {}

    # checkout no longer takes/sends a referral (issue #79): attribution is bound
    # at account-create, so its signature has no referral_code and no X-Vesta-Referral.
    def fake_checkout(self, *, token, plan, price, discount_code):
        captured.update(token=token, plan=plan, price=price, discount_code=discount_code)
        return {"url": "https://checkout.stripe.com/x", "subdomain": "ada", "server_id": "srv1"}

    monkeypatch.setattr(cli_mod.Client, "checkout", fake_checkout)
    rc, data = _run(["checkout", "--email", E, "--price", "200", "--code", " friend50 "], capsys)
    assert rc == 0 and data["url"].startswith("https://checkout.stripe.com/")
    assert captured == {"token": "TOK", "plan": "pro", "price": 200.0, "discount_code": "friend50"}
    # server_id is stashed for later steps but kept out of the agent-facing output.
    assert state_mod.load(E)["server_id"] == "srv1"
    assert "server_id" not in data


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


def test_create_agent_stashes_personality_and_seed(capsys, monkeypatch):
    _verified()
    _active_server(monkeypatch)
    captured = {}

    def fake_create(self, *, subdomain, server_token, name):
        captured.update(subdomain=subdomain, server_token=server_token, name=name)
        # vestad normalizes the name and returns the actual created name.
        return {"name": "ada"}

    monkeypatch.setattr(cli_mod.Client, "create_agent", fake_create)
    rc, data = _run(
        ["create-agent", "--email", E, "--name", "Ada", "--personality", "Dry", "--context", "designer in NYC; set up email and calendar"],
        capsys,
    )
    assert rc == 0 and data["created"] is True and data["name"] == "ada"
    # Create carries only the name now; vestad no longer accepts personality/seed at create time.
    assert captured == {"subdomain": "ada", "server_token": "VTOK", "name": "Ada"}
    # Personality + seed context are stashed for claude-finish to deliver via the config channel. The
    # NORMALIZED name vestad returned is stored so claude-finish addresses a path vestad accepts.
    stashed = state_mod.load(E)
    assert stashed["agent_name"] == "ada"
    assert stashed["personality"] == "dry"
    assert stashed["seed_context"] == "designer in NYC; set up email and calendar"


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
    # create-agent stashed the personality + seed context; claude-finish delivers them.
    state_mod.update(E, claude_session_id="CS", agent_name="Ada", personality="dry", seed_context="designer in NYC")
    _active_server(monkeypatch)
    monkeypatch.setattr(
        cli_mod.Client,
        "claude_oauth_complete",
        lambda self, *, subdomain, server_token, session_id, code: (
            "CREDS" if (session_id == "CS" and code == "PASTE") else pytest.fail("bad relay")
        ),
    )
    captured = {}

    def fake_set(self, *, subdomain, server_token, name, credentials, model, personality, seed_context):
        captured.update(name=name, credentials=credentials, model=model, personality=personality, seed_context=seed_context)
        return {"ok": True}

    monkeypatch.setattr(cli_mod.Client, "set_provider", fake_set)
    # No --model: the default is read from the box's vestad, not a hardcoded onboard constant.
    monkeypatch.setattr(cli_mod.Client, "fetch_agent_defaults", lambda self: {"model": "opus"})
    rc, data = _run(["claude-finish", "--email", E, "--code", "PASTE"], capsys)
    assert rc == 0 and data["connected"] is True and data["name"] == "Ada"
    assert captured == {
        "name": "Ada",
        "credentials": "CREDS",
        "model": "opus",
        "personality": "dry",
        "seed_context": "designer in NYC",
    }
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
    monkeypatch.setattr(cli_mod.Client, "fetch_agent_defaults", lambda self: {"model": "opus"})
    # The attach (set_provider) fails after OAuth was consumed on the VM.
    monkeypatch.setattr(
        cli_mod.Client,
        "set_provider",
        lambda self, *, subdomain, server_token, name, credentials, model, personality, seed_context: {"error": "bad gateway"},
    )
    rc, data = _run(["claude-finish", "--email", E, "--code", "PASTE"], capsys)
    assert rc == 2 and "claude-start" in data["error"]
    # The consumed session_id is forgotten (a retry must re-run claude-start), but
    # the buyer's session token survives so they aren't kicked out mid-onboard.
    assert "claude_session_id" not in state_mod.load(E)
    assert state_mod.token_for(E) == "TOK"


# --- error propagation ------------------------------------------------------


def test_unreachable_control_plane_exits_3(capsys, monkeypatch):
    _mock_precreate(monkeypatch)

    def boom(self, email):
        raise OnboardError("could not reach https://vesta.run/api")

    monkeypatch.setattr(cli_mod.Client, "send_otp", boom)
    rc, data = _run(["verify-send", "--email", E], capsys)
    assert rc == 3 and "could not reach" in data["error"]
