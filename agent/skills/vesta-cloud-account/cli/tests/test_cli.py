"""Tests for the account CLI — mocked client, no network."""

from __future__ import annotations

import json

import pytest
from vc_account_cli import cli as cli_mod
from vc_account_cli import referral_store
from vc_account_cli.client import AccountError


@pytest.fixture(autouse=True)
def _tmp_referral_store(tmp_path, monkeypatch):
    """Point the shared referral file at a throwaway path so tests never touch ~/.config."""
    monkeypatch.setattr(referral_store, "PATH", tmp_path / "referral_code")


def _run(argv, capsys):
    rc = cli_mod.main(argv)
    out = capsys.readouterr().out
    return rc, (json.loads(out) if out.strip() else None)


# --- plan -------------------------------------------------------------------


def test_plan_summarizes_and_adds_usd(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token", lambda self: "SITOK")
    monkeypatch.setattr(
        cli_mod.Client,
        "plan",
        lambda self, token: {
            "plan": "membership",
            "status": "active",
            "price_cents": 4800,
            "discount_percent": None,
            "subscription_status": "active",
            "renews_at": "2026-07-01T00:00:00.000Z",
            "region": "nbg1",
        },
    )
    rc, data = _run(["plan"], capsys)
    assert rc == 0
    assert data["plan"] == "membership"
    assert data["status"] == "active"
    # Friendly dollar figure derived from cents, raw cents preserved.
    assert data["price_usd"] == 48.0
    assert data["price_cents"] == 4800


def test_plan_surfaces_structured_error(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token", lambda self: "SITOK")
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token: {"error": "not a cloud-managed server"})
    rc, data = _run(["plan"], capsys)
    assert rc == 2 and data["error"] == "not a cloud-managed server"


# --- manage -----------------------------------------------------------------


def test_manage_returns_portal_link(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token", lambda self: "SITOK")
    monkeypatch.setattr(
        cli_mod.Client,
        "portal",
        lambda self, token: {"url": "https://billing.stripe.com/p/session/abc"},
    )
    rc, data = _run(["manage"], capsys)
    assert rc == 0
    assert data["url"].startswith("https://billing.stripe.com/")
    # The skill reminds the agent it only hands over a link.
    assert "you don't" in data["next"]


def test_manage_surfaces_no_billing_account(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token", lambda self: "SITOK")
    monkeypatch.setattr(cli_mod.Client, "portal", lambda self, token: {"error": "no_billing_account"})
    rc, data = _run(["manage"], capsys)
    assert rc == 2 and data["error"] == "no_billing_account"


# --- error propagation ------------------------------------------------------


def test_mint_failure_exits_3(capsys, monkeypatch):
    def boom(self):
        raise AccountError("not running inside an agent container (no VESTAD_PORT/AGENT_NAME)")

    monkeypatch.setattr(cli_mod.Client, "mint_token", boom)
    rc, data = _run(["plan"], capsys)
    assert rc == 3 and "not running inside an agent" in data["error"]


# --- referral -----------------------------------------------------------


def test_referral_reports_code_and_earnings(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token", lambda self: "SITOK")
    monkeypatch.setattr(
        cli_mod.Client,
        "plan",
        lambda self, token: {
            "plan": "membership",
            "referral_code": "ADA123",
            "referral_credit_cents": 1200,
            "invites_completed": 2,
        },
    )
    rc, data = _run(["referral"], capsys)
    assert rc == 0
    assert data == {
        "referral_code": "ADA123",
        "referral_credit_cents": 1200,
        "invites_completed": 2,
    }


def test_referral_surfaces_structured_error(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token", lambda self: "SITOK")
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token: {"error": "not a cloud-managed server"})
    rc, data = _run(["referral"], capsys)
    assert rc == 2 and data["error"] == "not a cloud-managed server"


def test_referral_not_hosted_surfaces_friendly_error(capsys, monkeypatch):
    def boom(self):
        raise AccountError("not a cloud-managed server")

    monkeypatch.setattr(cli_mod.Client, "mint_token", boom)
    rc, data = _run(["referral"], capsys)
    assert rc == 3
    assert data["error"] == "not_hosted"
    assert "set-referral --code" in data["message"]


# --- set-referral ---------------------------------------------------------


def test_set_referral_persists_code(capsys):
    rc, data = _run(["set-referral", "--code", " ADA123 "], capsys)
    assert rc == 0
    assert data == {"ok": True, "referral_code": "ADA123"}
    assert referral_store.get_referral_code() == "ADA123"


def test_set_referral_clear_removes_code(capsys):
    referral_store.set_referral_code("ADA123")
    rc, data = _run(["set-referral", "--clear"], capsys)
    assert rc == 0
    assert data == {"ok": True, "referral_code": None}
    assert referral_store.get_referral_code() is None


def test_set_referral_requires_exactly_one_of_code_or_clear(capsys):
    # Neither --code nor --clear: argparse's mutually exclusive required group
    # rejects it before the handler ever runs (its own exit code, 2).
    with pytest.raises(SystemExit) as exc_info:
        cli_mod.main(["set-referral"])
    assert exc_info.value.code == 2
