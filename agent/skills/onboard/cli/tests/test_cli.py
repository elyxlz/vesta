"""Tests for the onboard CLI — pure logic + a mocked control-plane client."""

from __future__ import annotations

import json


from onboard_cli import cli as cli_mod
from onboard_cli.client import OnboardError


def _run(argv, capsys):
    rc = cli_mod.main(argv)
    out = capsys.readouterr().out
    return rc, (json.loads(out) if out.strip() else None)


def test_links(capsys):
    rc, data = _run(["links"], capsys)
    assert rc == 0
    assert data["marketing"] == "https://vesta.run"
    assert "ios" in data and "android" in data and "desktop" in data


def test_presets(capsys):
    rc, data = _run(["presets"], capsys)
    assert rc == 0
    assert "dry" in data["personalities"]
    assert data["plans"] == ["starter", "pro", "power"]
    assert isinstance(data["skills"], list)


def test_start_rejects_bad_plan(capsys):
    rc, data = _run(
        ["start", "--email", "a@b.com", "--subdomain", "ada", "--plan", "enterprise"],
        capsys,
    )
    assert rc == 2
    assert "plan must be one of" in data["error"]


def test_check_calls_client(capsys, monkeypatch):
    seen = {}

    def fake_check(self, subdomain):
        seen["subdomain"] = subdomain
        return {"subdomain": subdomain, "available": True}

    monkeypatch.setattr(cli_mod.Client, "check", fake_check)
    rc, data = _run(["check", "Ada"], capsys)
    assert rc == 0
    assert seen["subdomain"] == "ada"  # normalised to lowercase
    assert data["available"] is True


def test_status_maps_availability(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "check", lambda self, s: {"subdomain": s, "available": True})
    rc, data = _run(["status", "--subdomain", "ada"], capsys)
    assert rc == 0 and data["status"] == "pending"

    monkeypatch.setattr(
        cli_mod.Client,
        "check",
        lambda self, s: {"subdomain": s, "available": False, "reason": "taken"},
    )
    rc, data = _run(["status", "--subdomain", "ada"], capsys)
    assert rc == 0 and data["status"] == "signed_up"


def test_start_builds_seed_and_forwards_referral(capsys, monkeypatch):
    captured = {}

    def fake_checkout(self, *, email, subdomain, plan, seed, referral_code, price=None, code=None):
        captured.update(
            email=email,
            subdomain=subdomain,
            plan=plan,
            seed=seed,
            referral_code=referral_code,
            price=price,
            code=code,
        )
        return {"url": "https://checkout.stripe.com/c/pay/cs_test_x"}

    monkeypatch.setattr(cli_mod.Client, "checkout", fake_checkout)
    rc, data = _run(
        [
            "start",
            "--email",
            "ada@example.com",
            "--subdomain",
            "Ada",
            "--plan",
            "Pro",
            "--name",
            "Ada",
            "--personality",
            "Dry",
            "--skills",
            "email-client, tasks ,",
            "--referral",
            "ref_abc",
        ],
        capsys,
    )
    assert rc == 0
    assert data["url"].startswith("https://checkout.stripe.com/")
    assert captured["subdomain"] == "ada" and captured["plan"] == "pro"
    assert captured["seed"] == {"name": "Ada", "personality": "dry", "skills": ["email-client", "tasks"]}
    assert captured["referral_code"] == "ref_abc"


def test_start_forwards_negotiated_price(capsys, monkeypatch):
    captured = {}

    def fake_checkout(self, *, email, subdomain, plan, seed, referral_code, price=None, code=None):
        captured["price"] = price
        return {"url": "https://checkout.stripe.com/c/pay/cs_test_x"}

    monkeypatch.setattr(cli_mod.Client, "checkout", fake_checkout)
    rc, data = _run(
        ["start", "--email", "vc@x.com", "--subdomain", "whale", "--plan", "power", "--price", "1500"],
        capsys,
    )
    assert rc == 0 and captured["price"] == 1500.0


def test_start_forwards_discount_code(capsys, monkeypatch):
    captured = {}

    def fake_checkout(self, *, email, subdomain, plan, seed, referral_code, price=None, code=None):
        captured["code"] = code
        return {"url": "https://checkout.stripe.com/c/pay/cs_test_x"}

    monkeypatch.setattr(cli_mod.Client, "checkout", fake_checkout)
    rc, data = _run(
        ["start", "--email", "a@x.com", "--subdomain", "ada", "--code", "  friend50 "],
        capsys,
    )
    assert rc == 0 and captured["code"] == "friend50"


def test_start_rejects_price_below_floor(capsys, monkeypatch):
    called = {"n": 0}

    def fake_checkout(self, **kw):
        called["n"] += 1
        return {"url": "x"}

    monkeypatch.setattr(cli_mod.Client, "checkout", fake_checkout)
    # pro floor is $24; $5 must be rejected locally, before any checkout call.
    rc, data = _run(
        ["start", "--email", "a@b.com", "--subdomain", "ada", "--plan", "pro", "--price", "5"],
        capsys,
    )
    assert rc == 2
    assert "below the pro floor" in data["error"] and data["floor_usd"] == 24
    assert called["n"] == 0


def test_start_at_floor_is_allowed(capsys, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        cli_mod.Client,
        "checkout",
        lambda self, **kw: captured.update(kw) or {"url": "https://checkout.stripe.com/x"},
    )
    rc, _ = _run(
        ["start", "--email", "a@b.com", "--subdomain", "ada", "--plan", "starter", "--price", "12"],
        capsys,
    )
    assert rc == 0 and captured["price"] == 12.0


def test_presets_includes_floors(capsys):
    rc, data = _run(["presets"], capsys)
    assert rc == 0
    assert data["plan_floor_usd"] == {"starter": 12, "pro": 24, "power": 48}


def test_start_surfaces_structured_error(capsys, monkeypatch):
    monkeypatch.setattr(
        cli_mod.Client,
        "checkout",
        lambda self, **kw: {"error": "subdomain taken"},
    )
    rc, data = _run(["start", "--email", "a@b.com", "--subdomain", "ada", "--plan", "starter"], capsys)
    assert rc == 2 and data["error"] == "subdomain taken"


def test_unreachable_control_plane_exits_3(capsys, monkeypatch):
    def boom(self, subdomain):
        raise OnboardError("could not reach the control plane")

    monkeypatch.setattr(cli_mod.Client, "check", boom)
    rc, data = _run(["check", "ada"], capsys)
    assert rc == 3 and "could not reach" in data["error"]
