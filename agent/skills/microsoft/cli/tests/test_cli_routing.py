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


def _dispatch_args(**over):
    base = dict(command="list", account="me@example.com", folder="inbox", limit=10, search=None, backend=backend.GRAPH)
    base.update(over)
    return SimpleNamespace(**base)


def test_email_list_with_search_dispatches_to_search(monkeypatch):
    """`email list --search "x"` must run the search path, not the plain list path."""
    seen = {}
    monkeypatch.setattr(cli.email, "search_emails", lambda cfg, client, **kw: seen.update(kw) or "searched")
    monkeypatch.setattr(cli.email, "list_emails", lambda *a, **k: "listed")

    result = cli._dispatch_email(_dispatch_args(search="cancellation"), Config(), client=None)

    assert result == "searched"
    # Same call shape as `email search --query`: query passed through, folder defaults to all.
    assert seen == dict(account_email="me@example.com", query="cancellation", limit=10, folder=None)


def test_email_list_search_respects_explicit_folder(monkeypatch):
    monkeypatch.setattr(cli.email, "search_emails", lambda cfg, client, **kw: kw)
    monkeypatch.setattr(cli.email, "list_emails", lambda *a, **k: "listed")

    result = cli._dispatch_email(_dispatch_args(search="foo", folder="archive"), Config(), client=None)

    assert result["folder"] == "archive"


def test_email_list_without_search_is_plain_list(monkeypatch):
    monkeypatch.setattr(cli.email, "search_emails", lambda *a, **k: "searched")
    monkeypatch.setattr(cli.email, "list_emails", lambda cfg, client, **kw: "listed")

    assert cli._dispatch_email(_dispatch_args(search=None), Config(), client=None) == "listed"


def test_email_list_search_flag_parses():
    """The parser must accept --search (and its --query alias) on the list subcommand."""
    parser = cli.build_parser()
    args = parser.parse_args(["email", "list", "--account", "me@example.com", "--search", "hi"])
    assert args.command == "list"
    assert args.search == "hi"

    aliased = parser.parse_args(["email", "list", "--account", "me@example.com", "--query", "hi"])
    assert aliased.search == "hi"
