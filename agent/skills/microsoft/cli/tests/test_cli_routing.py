"""Locks the two-backend selection logic in cli._route (graph vs owa-rest)."""

from types import SimpleNamespace

from microsoft_cli import cli, backend
from microsoft_cli.config import Config


def _args(choice):
    return SimpleNamespace(backend=choice, account="me@example.com")


def _fns(calls):
    return (lambda: calls.append("graph") or "graph", lambda: calls.append("rest") or "rest")


def test_forced_graph_never_touches_rest(monkeypatch):
    monkeypatch.setattr(cli.owa_rest, "has_valid_token", lambda *a, **k: True)
    calls = []
    graph_fn, rest_fn = _fns(calls)
    assert cli._route(_args(backend.GRAPH), Config(), "me@example.com", graph_fn, rest_fn) == "graph"
    assert calls == ["graph"]


def test_forced_owa_rest_never_touches_graph(monkeypatch):
    calls = []
    graph_fn, rest_fn = _fns(calls)
    assert cli._route(_args(backend.OWA_REST), Config(), "me@example.com", graph_fn, rest_fn) == "rest"
    assert calls == ["rest"]


def test_auto_without_rest_token_runs_graph_only(monkeypatch):
    monkeypatch.setattr(cli.owa_rest, "has_valid_token", lambda *a, **k: False)
    calls = []
    graph_fn, rest_fn = _fns(calls)
    assert cli._route(_args(backend.AUTO), Config(), "me@example.com", graph_fn, rest_fn) == "graph"
    assert calls == ["graph"]


def test_auto_rest_only_account_goes_straight_to_rest(monkeypatch):
    monkeypatch.setattr(cli.owa_rest, "has_valid_token", lambda *a, **k: True)
    monkeypatch.setattr(cli, "_graph_has_account", lambda *a, **k: False)
    calls = []
    graph_fn, rest_fn = _fns(calls)
    assert cli._route(_args(backend.AUTO), Config(), "me@example.com", graph_fn, rest_fn) == "rest"
    assert calls == ["rest"]


def test_auto_falls_back_to_rest_on_permission_error(monkeypatch):
    monkeypatch.setattr(cli.owa_rest, "has_valid_token", lambda *a, **k: True)
    monkeypatch.setattr(cli, "_graph_has_account", lambda *a, **k: True)
    calls = []

    def graph_fn():
        calls.append("graph")
        raise PermissionError("blocked")

    def rest_fn():
        calls.append("rest")
        return "rest"

    assert cli._route(_args(backend.AUTO), Config(), "me@example.com", graph_fn, rest_fn) == "rest"
    assert calls == ["graph", "rest"]
