"""A result that was cut short must SAY so, on both of the paths that cut one short.

`--limit` is a hard cap, not a page size, so a caller who lists a date window and gets back
exactly `limit` items has seen an arbitrary newest-first slice of it. Nothing in the output
distinguishes that from having seen the whole window, and the natural reading is the wrong
one. It becomes a false negative the moment anyone concludes something from what is ABSENT:
no booking, no reply, no invoice in that window.

`MAX_FILTER_SCAN` is the second, quieter path: a client-side query gives up after scanning a
fixed number of messages and returns a SHORT list, so not even the count hints that the
window went unread.

The warnings go to stderr so `--json` stays machine-parseable, and these tests pin both
halves: that they fire when a result really was cut short, and that they stay quiet
everywhere else. A warning that fired on every call would be trained out within a day.
"""

import json
from types import SimpleNamespace

from microsoft_cli import cli


def _run(capsys, result, **kw):
    args = SimpleNamespace(group="email", command="list", json=True, json_pretty=False, **kw)
    cli._print_result(args, result)
    cap = capsys.readouterr()
    return cap.out, cap.err


def test_exactly_at_the_limit_warns(capsys):
    _out, err = _run(capsys, [{"id": i} for i in range(400)], limit=400)
    assert "TRUNCATED" in err
    assert "400" in err


def test_under_the_limit_is_silent(capsys):
    _out, err = _run(capsys, [{"id": i} for i in range(161)], limit=400)
    assert err == ""


def test_empty_result_is_silent(capsys):
    """A genuinely empty window is not a truncation, and calling it one would teach the
    reader to distrust the one signal that matters."""
    _out, err = _run(capsys, [], limit=400)
    assert err == ""


def test_command_without_a_limit_does_not_crash(capsys):
    _out, err = _run(capsys, [{"id": 1}])
    assert err == ""


def test_warning_never_contaminates_json_on_stdout(capsys):
    """Every caller that pipes --json into a parser would break if this landed on stdout."""
    out, err = _run(capsys, [{"id": i} for i in range(5)], limit=5)
    assert "TRUNCATED" in err
    assert "TRUNCATED" not in out
    assert len(json.loads(out)) == 5


def test_non_list_results_are_ignored(capsys):
    """A single message or a status dict has no cap to hit."""
    _out, err = _run(capsys, {"id": "one-message"}, limit=1)
    assert err == ""


def _filter_run(capsys, monkeypatch, *, yielded, query, limit):
    """Drive _filter_mailbox_messages with a fake pager, returning its stderr."""
    from microsoft_cli import email as email_mod

    monkeypatch.setattr(email_mod.graph, "paginate_cfg", lambda *a, **k: iter(yielded))
    monkeypatch.setattr(email_mod, "_scrub_email_snapshot", lambda e: None)
    monkeypatch.setattr(email_mod.graph, "localize_datetime_fields", lambda e: None)
    out = email_mod._filter_mailbox_messages(None, None, "acct", "endpoint", since="2026-08-01", until=None, query=query, limit=limit)
    return out, capsys.readouterr().err


def test_scan_cap_warns_even_though_the_result_is_short(capsys, monkeypatch):
    """The dangerous one: the count is UNDER --limit, so nothing about a short list says the
    window went unread. A caller asking 'did they ever reply' gets a confident false negative."""
    from microsoft_cli import email as email_mod

    haystack = [{"subject": "nothing relevant", "bodyPreview": "", "from": {}} for _ in range(email_mod.MAX_FILTER_SCAN + 50)]
    out, err = _filter_run(capsys, monkeypatch, yielded=haystack, query="needle", limit=400)
    assert out == []
    assert "TRUNCATED" in err
    assert "MAX_FILTER_SCAN" in err


def test_short_window_fully_read_is_silent(capsys, monkeypatch):
    """A window that genuinely ran out of mail must NOT be labelled truncated."""
    haystack = [{"subject": "nothing relevant", "bodyPreview": "", "from": {}} for _ in range(10)]
    out, err = _filter_run(capsys, monkeypatch, yielded=haystack, query="needle", limit=400)
    assert out == []
    assert err == ""


def test_filling_the_limit_does_not_claim_the_scan_cap(capsys, monkeypatch):
    """Stopping because the caller's --limit was reached is a different event from giving up
    on the scan, and conflating them would make the message a lie about which cap bit."""
    haystack = [{"subject": "needle here", "bodyPreview": "", "from": {}} for _ in range(20)]
    out, err = _filter_run(capsys, monkeypatch, yielded=haystack, query="needle", limit=5)
    assert len(out) == 5
    assert err == ""
