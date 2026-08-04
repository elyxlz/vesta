"""Tests for the vesta-cloud CLI — mocked client, no network."""

from __future__ import annotations

import json

import pytest
from vesta_cloud_cli import cli as cli_mod
from vesta_cloud_cli import referral_store
from vesta_cloud_cli.client import AccountError


@pytest.fixture(autouse=True)
def _tmp_referral_store(tmp_path, monkeypatch):
    """Point the shared referral file at a throwaway path so tests never touch ~/.config."""
    monkeypatch.setattr(referral_store, "PATH", tmp_path / "referral_code")


def _run(argv, capsys):
    """A failure prints on stderr with stdout untouched; success prints on stdout alone."""
    rc = cli_mod.main(argv)
    captured = capsys.readouterr()
    if rc == 0:
        assert captured.err == ""
        payload = captured.out
    else:
        assert captured.out == ""
        payload = captured.err
    return rc, (json.loads(payload) if payload.strip() else None)


# --- whoami -----------------------------------------------------------------


def test_whoami_account_true_when_minted_and_active(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "account_token", lambda self: {"token": "SITOK", "expires_in": 600})
    monkeypatch.setattr(
        cli_mod.Client,
        "plan",
        lambda self, token, control_url=None: {
            "plan": "membership",
            "status": "active",
            "price_cents": 4800,
            "renews_at": "2026-07-01T00:00:00.000Z",
        },
    )
    rc, data = _run(["whoami"], capsys)
    assert rc == 0
    assert data["account"] is True
    assert data["plan"] == "membership" and data["status"] == "active"
    assert data["price_usd"] == 48.0


def test_whoami_account_false_when_mint_refused(capsys, monkeypatch):
    # A reached vestad refusing to mint (no account) is a valid answer, exit 0.
    # "no server identity available" is vestad's actual 404 body for the miss.
    monkeypatch.setattr(cli_mod.Client, "account_token", lambda self: {"error": "no server identity available"})
    rc, data = _run(["whoami"], capsys)
    assert rc == 0
    assert data["account"] is False
    assert data["reason"] == "no server identity available"


def test_whoami_suspended_is_account_true_with_status(capsys, monkeypatch):
    # A recognized but suspended box answers /account 200 with status "suspended"
    # (not an error), so it is paired (account:true); status carries the nuance.
    monkeypatch.setattr(cli_mod.Client, "account_token", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token, control_url=None: {"plan": "membership", "status": "suspended"})
    rc, data = _run(["whoami"], capsys)
    assert rc == 0
    assert data["account"] is True and data["status"] == "suspended"


def test_whoami_account_false_when_control_plane_refuses_the_read(capsys, monkeypatch):
    # Minted locally but /account refused (e.g. a stale link whose row was
    # removed on the dashboard -> 401 unauthenticated). Suspended/unpaid boxes
    # are NOT this case: /account answers 200 for them (see the test above).
    monkeypatch.setattr(cli_mod.Client, "account_token", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token, control_url=None: {"error": "unauthenticated"})
    rc, data = _run(["whoami"], capsys)
    assert rc == 0
    assert data["account"] is False and data["reason"] == "unauthenticated"


def test_whoami_outage_exits_3(capsys, monkeypatch):
    # A genuine transport failure is NOT "no account" — it must surface as exit 3.
    def boom(self):
        raise AccountError("could not reach vestad: timeout")

    monkeypatch.setattr(cli_mod.Client, "account_token", boom)
    rc, data = _run(["whoami"], capsys)
    assert rc == 3 and "could not reach" in data["error"]


# --- token ------------------------------------------------------------------


def test_token_returns_credential_and_control_url(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", lambda self: {"token": "SITOK", "expires_in": 600})
    rc, data = _run(["token"], capsys)
    assert rc == 0
    assert data["token"] == "SITOK" and data["expires_in"] == 600
    assert data["control_url"].startswith("https://")


def test_token_no_account_exits_3(capsys, monkeypatch):
    def boom(self):
        raise AccountError("no server identity available")

    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", boom)
    rc, data = _run(["token"], capsys)
    assert rc == 3 and "no server identity" in data["error"]


# --- plan -------------------------------------------------------------------


def test_plan_summarizes_and_adds_usd(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(
        cli_mod.Client,
        "plan",
        lambda self, token, control_url=None: {
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
    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token, control_url=None: {"error": "unauthenticated"})
    rc, data = _run(["plan"], capsys)
    assert rc == 2 and data["error"] == "unauthenticated"


# --- manage -----------------------------------------------------------------


def test_manage_returns_portal_link(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(
        cli_mod.Client,
        "portal",
        lambda self, token, control_url=None: {"url": "https://billing.stripe.com/p/session/abc"},
    )
    rc, data = _run(["manage"], capsys)
    assert rc == 0
    assert data["url"].startswith("https://billing.stripe.com/")
    # The skill reminds the agent it only hands over a link.
    assert "you don't" in data["next"]


def test_manage_surfaces_no_billing_account(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(cli_mod.Client, "portal", lambda self, token, control_url=None: {"error": "no_billing_account"})
    rc, data = _run(["manage"], capsys)
    assert rc == 2 and data["error"] == "no_billing_account"


# --- error propagation ------------------------------------------------------


def test_mint_failure_exits_3(capsys, monkeypatch):
    def boom(self):
        raise AccountError("not running inside an agent container (no VESTAD_PORT/BOX_HOST/AGENT_NAME/AGENT_TOKEN)")

    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", boom)
    rc, data = _run(["plan"], capsys)
    assert rc == 3 and "not running inside an agent" in data["error"]


# --- referral -----------------------------------------------------------


def test_referral_reports_code_and_earnings(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(
        cli_mod.Client,
        "plan",
        lambda self, token, control_url=None: {
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
    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token, control_url=None: {"error": "unauthenticated"})
    rc, data = _run(["referral"], capsys)
    assert rc == 2 and data["error"] == "unauthenticated"


def test_referral_not_hosted_surfaces_friendly_error(capsys, monkeypatch):
    def boom(self):
        raise AccountError("no server identity available")

    monkeypatch.setattr(cli_mod.Client, "mint_token_detail", boom)
    rc, data = _run(["referral"], capsys)
    assert rc == 3
    assert data["error"] == "not_hosted"
    assert "set-referral --code" in data["message"]


# --- login / logout ---------------------------------------------------------


def _read_json_docs(out: str) -> list[dict]:
    """`login` prints TWO json documents (the code relay, then the confirmation)."""
    docs, decoder, i = [], json.JSONDecoder(), 0
    while i < len(out):
        while i < len(out) and out[i].isspace():
            i += 1
        if i >= len(out):
            break
        doc, end = decoder.raw_decode(out, i)
        docs.append(doc)
        i = end
    return docs


def test_login_relays_code_then_links(capsys, monkeypatch):
    monkeypatch.setattr(
        cli_mod.Client,
        "pair_start",
        lambda self: {"user_code": "BCDF-2345", "verification_url": "https://vesta.run/pair?code=BCDF-2345", "interval": 5, "expires_in": 600},
    )
    # Both pending shapes that exist on the wire (200 {"status": "pending"}
    # and a 409 whose message contains "pending"), then linked; both must loop.
    polls = iter(
        [
            {"status": "pending"},
            {"error": "authorization is still pending"},
            {"status": "linked", "server_id": "srv_1", "control_url": "https://vesta.run/api"},
        ]
    )
    monkeypatch.setattr(cli_mod.Client, "pair_poll", lambda self: next(polls))
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    # The post-link confirmation is whoami's flow.
    monkeypatch.setattr(cli_mod.Client, "account_token", lambda self: {"token": "SITOK", "control_url": "https://vesta.run/api"})
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token, control_url=None: {"plan": "services", "status": "active"})

    rc = cli_mod.main(["login"])
    docs = _read_json_docs(capsys.readouterr().out)
    assert rc == 0
    assert docs[0]["user_code"] == "BCDF-2345"
    assert docs[0]["verification_url"].endswith("code=BCDF-2345")
    assert "give the owner" in docs[0]["next"]
    assert docs[-1]["account"] is True and docs[-1]["plan"] == "services"


def test_login_surfaces_start_error(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "pair_start", lambda self: {"error": "already paired to a Vesta Cloud account (unpair first)"})
    rc, data = _run(["login"], capsys)
    assert rc == 2 and "already paired" in data["error"]


def test_login_gives_up_on_terminal_poll_error(capsys, monkeypatch):
    monkeypatch.setattr(
        cli_mod.Client,
        "pair_start",
        lambda self: {"user_code": "BCDF-2345", "verification_url": "https://vesta.run/pair?code=BCDF-2345", "interval": 5, "expires_in": 600},
    )
    calls = {"n": 0}

    def poll(self):
        calls["n"] += 1
        return {"error": "pairing failed: already_has_server"}

    monkeypatch.setattr(cli_mod.Client, "pair_poll", poll)
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    rc = cli_mod.main(["login"])
    captured = capsys.readouterr()
    assert rc == 2
    assert calls["n"] == 1  # a terminal refusal stops the loop immediately
    # The code relay stays on stdout; the refusal itself lands on stderr.
    assert _read_json_docs(captured.out)[0]["user_code"] == "BCDF-2345"
    assert "already_has_server" in json.loads(captured.err)["error"]


def test_login_times_out(capsys, monkeypatch):
    monkeypatch.setattr(
        cli_mod.Client,
        "pair_start",
        lambda self: {"user_code": "BCDF-2345", "verification_url": "https://vesta.run/pair?code=BCDF-2345", "interval": 5, "expires_in": 600},
    )
    monkeypatch.setattr(cli_mod.Client, "pair_poll", lambda self: {"status": "pending"})
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    # A monotonic clock that jumps past the deadline after the first poll.
    ticks = iter([0.0, 1.0, 10_000.0])
    monkeypatch.setattr(cli_mod.time, "monotonic", lambda: next(ticks, 10_000.0))
    rc = cli_mod.main(["login"])
    captured = capsys.readouterr()
    assert rc == 2
    assert json.loads(captured.err)["error"] == "pairing timed out"


def test_login_survives_transient_poll_failures(capsys, monkeypatch):
    monkeypatch.setattr(
        cli_mod.Client,
        "pair_start",
        lambda self: {"user_code": "BCDF-2345", "verification_url": "https://vesta.run/pair?code=BCDF-2345", "interval": 5, "expires_in": 600},
    )
    calls = {"n": 0}

    def poll(self):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AccountError("server error 502: control plane blip")
        if calls["n"] == 2:
            return {"status": "pending"}
        return {"status": "linked", "server_id": "srv_1", "control_url": "https://vesta.run/api"}

    monkeypatch.setattr(cli_mod.Client, "pair_poll", poll)
    monkeypatch.setattr(cli_mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(cli_mod.Client, "account_token", lambda self: {"token": "SITOK"})
    monkeypatch.setattr(cli_mod.Client, "plan", lambda self, token, control_url=None: {"plan": "services", "status": "active"})

    rc = cli_mod.main(["login"])
    docs = _read_json_docs(capsys.readouterr().out)
    assert rc == 0
    assert calls["n"] == 3  # the 502 was retried, not fatal
    assert docs[-1]["account"] is True


def test_login_reports_linked_when_confirmation_read_fails(capsys, monkeypatch):
    monkeypatch.setattr(
        cli_mod.Client,
        "pair_start",
        lambda self: {"user_code": "BCDF-2345", "verification_url": "https://vesta.run/pair?code=BCDF-2345", "interval": 5, "expires_in": 600},
    )
    monkeypatch.setattr(
        cli_mod.Client,
        "pair_poll",
        lambda self: {"status": "linked", "server_id": "srv_1", "control_url": "https://vesta.run/api"},
    )

    def boom(self):
        raise AccountError("could not reach vestad: timeout")

    monkeypatch.setattr(cli_mod.Client, "account_token", boom)

    rc = cli_mod.main(["login"])
    docs = _read_json_docs(capsys.readouterr().out)
    # The pairing succeeded; a flaky confirmation must NOT fail the command
    # (a nonzero exit invites a destructive logout + retry).
    assert rc == 0
    assert docs[-1]["status"] == "linked" and docs[-1]["server_id"] == "srv_1"
    assert "whoami" in docs[-1]["note"]


def test_logout_success(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "unpair", lambda self: {"status": "unpaired"})
    rc, data = _run(["logout"], capsys)
    assert rc == 0 and data == {"status": "unpaired"}


def test_logout_not_paired_exits_2(capsys, monkeypatch):
    monkeypatch.setattr(cli_mod.Client, "unpair", lambda self: {"error": "not paired to a Vesta Cloud account"})
    rc, data = _run(["logout"], capsys)
    assert rc == 2 and "not paired" in data["error"]


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
