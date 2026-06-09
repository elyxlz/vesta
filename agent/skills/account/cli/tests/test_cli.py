"""Tests for the account CLI — mocked client, no network."""

from __future__ import annotations

import json

from account_cli import cli as cli_mod
from account_cli.client import AccountError


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
