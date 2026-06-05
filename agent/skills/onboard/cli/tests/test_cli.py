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

    def fake_checkout(self, *, email, subdomain, plan, seed, referral_code):
        captured.update(email=email, subdomain=subdomain, plan=plan, seed=seed, referral_code=referral_code)
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
