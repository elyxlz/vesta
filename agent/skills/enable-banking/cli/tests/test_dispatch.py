"""Behavior-locking tests for the CLI dispatch + handlers (faked config + client).

Drives the real `main()` entry point so the locks survive any change to the
internal command routing.
"""

import json
import sys

import pytest

from finance_cli import cli


def run(monkeypatch, capsys, argv, conf, eb_patches=None):
    saved: dict = {}
    monkeypatch.setattr(cli.cfg, "load", lambda: dict(conf))
    monkeypatch.setattr(cli.cfg, "save", lambda c: saved.update({"conf": c}))
    for name, fn in (eb_patches or {}).items():
        monkeypatch.setattr(cli.eb, name, fn)
    monkeypatch.setattr(sys, "argv", ["finance", *argv])
    cli.main()
    return json.loads(capsys.readouterr().out), saved


def test_config_show(monkeypatch, capsys):
    conf = {"app_id": "a1", "key_path": "/k.pem", "session_id": "s1", "accounts": [{"uid": "u1"}]}
    out, _ = run(monkeypatch, capsys, ["config", "show"], conf)
    assert out == {
        "app_id": "a1",
        "key_path": "/k.pem",
        "aspsp_name": "",
        "aspsp_country": "",
        "session_id": "***",
        "accounts": [{"uid": "u1"}],
    }


def test_config_set(monkeypatch, capsys):
    out, saved = run(monkeypatch, capsys, ["config", "set", "--app-id", "new", "--key-path", "/p.pem"], {})
    assert out["status"] == "saved"
    assert out["config"]["app_id"] == "new"
    assert out["config"]["key_path"] == "/p.pem"
    assert saved["conf"]["app_id"] == "new"


def test_auth_status_no_session(monkeypatch, capsys):
    conf = {"app_id": "a1", "key_path": "/k.pem", "session_id": "", "accounts": []}
    out, _ = run(monkeypatch, capsys, ["auth", "status"], conf)
    assert out["credentials_configured"] is True
    assert out["session_active"] is False
    assert out["accounts_count"] == 0


def test_accounts_lists_stored(monkeypatch, capsys):
    accounts = [{"uid": "u1", "name": "Main", "currency": "GBP"}]
    conf = {"app_id": "a1", "key_path": "/k.pem", "session_id": "s1", "accounts": accounts}
    out, _ = run(monkeypatch, capsys, ["accounts"], conf)
    assert out == accounts


def test_balances(monkeypatch, capsys):
    accounts = [{"uid": "u1", "name": "Main", "currency": "GBP"}]
    conf = {"app_id": "a1", "key_path": "/k.pem", "session_id": "s1", "accounts": accounts}
    out, _ = run(
        monkeypatch,
        capsys,
        ["balances"],
        conf,
        {"get_balances": lambda c, uid: [{"balance_amount": {"amount": "5"}}]},
    )
    assert out == [{"uid": "u1", "name": "Main", "currency": "GBP", "balances": [{"balance_amount": {"amount": "5"}}]}]


def test_transactions_list_sorts_and_tags(monkeypatch, capsys):
    accounts = [{"uid": "u1", "name": "Main", "currency": "GBP"}]
    conf = {"app_id": "a1", "key_path": "/k.pem", "session_id": "s1", "accounts": accounts}
    txns = [
        {"booking_date": "2026-01-01", "id": "old"},
        {"booking_date": "2026-02-01", "id": "new"},
    ]
    out, _ = run(
        monkeypatch,
        capsys,
        ["transactions", "list", "--days", "30"],
        conf,
        {"get_transactions": lambda c, uid, date_from, date_to: list(txns)},
    )
    assert [t["id"] for t in out] == ["new", "old"]
    assert out[0]["_account_uid"] == "u1"
    assert out[0]["_account_name"] == "Main"


def test_summary_aggregates(monkeypatch, capsys):
    accounts = [{"uid": "u1", "name": "Main", "currency": "GBP"}]
    conf = {"app_id": "a1", "key_path": "/k.pem", "session_id": "s1", "accounts": accounts}
    txns = [
        {"credit_debit_indicator": "DBIT", "transaction_amount": {"amount": "10"}, "creditor_name": "Shop"},
        {"credit_debit_indicator": "DBIT", "transaction_amount": {"amount": "5"}, "creditor_name": "Shop"},
        {"credit_debit_indicator": "CRDT", "transaction_amount": {"amount": "99"}, "creditor_name": "Pay"},
    ]
    out, _ = run(
        monkeypatch,
        capsys,
        ["summary", "--month", "2026-03"],
        conf,
        {"get_transactions": lambda c, uid, date_from, date_to: list(txns)},
    )
    assert out["grand_total"] == 15.0
    assert out["transaction_count"] == 2
    assert out["categories"] == [{"category": "Shop", "total": 15.0, "count": 2}]
    assert out["period"] == {"from": "2026-03-01", "to": "2026-04-01"}


def test_accounts_requires_session_exits(monkeypatch, capsys):
    conf = {"app_id": "a1", "key_path": "/k.pem", "session_id": "", "accounts": []}
    with pytest.raises(SystemExit):
        run(monkeypatch, capsys, ["accounts"], conf)
