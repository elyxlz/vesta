"""A mail result that can hide more mail says so on stderr, and stays silent everywhere else.

Three gaps: a list holding exactly --limit items, an empty unfoldered search (Graph $search
skips Junk Email and Deleted Items), and a client-side query that stopped at MAX_FILTER_SCAN.
"""

import json
from types import SimpleNamespace

from microsoft_cli import cli, email, owa_rest_commands


def _run(capsys, result, *, group="email", command="list", search=None, **kw):
    args = SimpleNamespace(group=group, command=command, json=True, json_pretty=False, search=search, **kw)
    cli._print_result(args, result)
    cap = capsys.readouterr()
    return cap.out, cap.err


# --- the --limit cap -------------------------------------------------------------------------


def test_exactly_at_the_limit_warns(capsys):
    _out, err = _run(capsys, [{"id": i} for i in range(400)], limit=400)
    assert "more may exist" in err
    assert "400" in err


def test_under_the_limit_is_silent(capsys):
    _out, err = _run(capsys, [{"id": i} for i in range(161)], limit=400)
    assert err == ""


def test_empty_result_is_silent(capsys):
    _out, err = _run(capsys, [], limit=400)
    assert err == ""


def test_command_without_a_limit_does_not_crash(capsys):
    _out, err = _run(capsys, [{"id": 1}])
    assert err == ""


def test_warning_never_contaminates_json_on_stdout(capsys):
    out, err = _run(capsys, [{"id": i} for i in range(5)], limit=5)
    assert "more may exist" in err
    assert "more may exist" not in out
    assert len(json.loads(out)) == 5


def test_non_list_results_are_ignored(capsys):
    _out, err = _run(capsys, {"id": "one-message"}, limit=1)
    assert err == ""


# --- the search scope ------------------------------------------------------------------------


def test_empty_mailbox_wide_search_warns_about_junk(capsys):
    _out, err = _run(capsys, [], command="search", limit=10, folder=None)
    assert "Junk Email" in err
    assert "Deleted Items" in err


def test_empty_search_scoped_to_a_folder_is_silent(capsys):
    _out, err = _run(capsys, [], command="search", limit=10, folder="junk")
    assert err == ""


def test_search_with_results_is_silent(capsys):
    _out, err = _run(capsys, [{"id": "a"}], command="search", limit=10, folder=None)
    assert err == ""


def test_empty_list_query_warns_because_it_runs_the_same_search(capsys):
    _out, err = _run(capsys, [], command="list", limit=10, folder="inbox", search="someone@x.com")
    assert "Junk Email" in err
    assert "Deleted Items" in err
    assert "--folder junk" in err


def test_empty_list_query_scoped_to_a_folder_is_silent(capsys):
    _out, err = _run(capsys, [], command="list", limit=10, folder="junk", search="someone@x.com")
    assert err == ""


def test_empty_list_without_a_query_stays_silent(capsys):
    _out, err = _run(capsys, [], command="list", limit=10, folder="inbox", search=None)
    assert err == ""


def test_real_parsed_args_from_both_routes_warn(capsys):
    parser = cli.build_parser()
    for argv in (
        ["email", "search", "--account", "me@example.com", "--query", "someone@x.com"],
        ["email", "list", "--account", "me@example.com", "--query", "someone@x.com"],
    ):
        cli._print_result(parser.parse_args(argv), [])
        assert "Junk Email" in capsys.readouterr().err


def test_both_warnings_can_fire_independently(capsys):
    _out, err = _run(capsys, [{"id": i} for i in range(10)], command="search", limit=10, folder=None)
    assert "more may exist" in err
    assert "Junk Email" not in err


# --- the scan cap ----------------------------------------------------------------------------


def _filter_run(capsys, monkeypatch, *, yielded, query, limit):
    monkeypatch.setattr(email.graph, "paginate_cfg", lambda *a, **k: iter(yielded))
    monkeypatch.setattr(email, "_scrub_email_snapshot", lambda e: None)
    monkeypatch.setattr(email.graph, "localize_datetime_fields", lambda e: None)
    out = email._filter_mailbox_messages(None, None, "acct", "endpoint", since="2026-08-01", until=None, query=query, limit=limit)
    return out, capsys.readouterr().err


def _unmatched(count):
    return [{"subject": "nothing relevant", "bodyPreview": "", "from": {}} for _ in range(count)]


def test_scan_cap_warns_even_though_the_result_is_short(capsys, monkeypatch):
    out, err = _filter_run(capsys, monkeypatch, yielded=_unmatched(email.MAX_FILTER_SCAN + 50), query="needle", limit=400)
    assert out == []
    assert "MAX_FILTER_SCAN" in err
    assert str(email.MAX_FILTER_SCAN) in err


def test_short_window_fully_read_is_silent(capsys, monkeypatch):
    out, err = _filter_run(capsys, monkeypatch, yielded=_unmatched(10), query="needle", limit=400)
    assert out == []
    assert err == ""


def test_filling_the_limit_does_not_claim_the_scan_cap(capsys, monkeypatch):
    haystack = [{"subject": "needle here", "bodyPreview": "", "from": {}} for _ in range(20)]
    out, err = _filter_run(capsys, monkeypatch, yielded=haystack, query="needle", limit=5)
    assert len(out) == 5
    assert err == ""


def test_owa_rest_scan_cap_warns_on_a_short_result(capsys, monkeypatch):
    monkeypatch.setattr(owa_rest_commands.owa_rest, "filter_messages_by_date", lambda *a, **k: _unmatched(email.MAX_FILTER_SCAN))
    out = owa_rest_commands.search_emails(None, None, account_email="me@x.com", query="needle", limit=400, since="2026-08-01")
    assert out == []
    assert "MAX_FILTER_SCAN" in capsys.readouterr().err


def test_owa_rest_window_fully_read_is_silent(capsys, monkeypatch):
    monkeypatch.setattr(owa_rest_commands.owa_rest, "filter_messages_by_date", lambda *a, **k: _unmatched(10))
    out = owa_rest_commands.search_emails(None, None, account_email="me@x.com", query="needle", limit=400, since="2026-08-01")
    assert out == []
    assert capsys.readouterr().err == ""
