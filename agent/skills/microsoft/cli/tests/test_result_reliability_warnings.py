"""A mail result that is not what it looks like must SAY so.

Two different ways a mailbox result misleads, and neither is visible in the output:

1. **`--limit` is a hard cap, not a page size.** A caller who lists a date window and gets back
   exactly `limit` items has seen an arbitrary newest-first slice of it. That is byte-for-byte
   indistinguishable from having seen the whole window, and the natural reading is the wrong one.

2. **`$search` does not reach Junk Email or Deleted Items.** Graph's `$search` over `/me/messages`
   skips both, so an empty search result reads as "this was never sent" when it only means "not in
   the folders `$search` covers". Two subcommands take that route: `email search --query` and the
   `email list --query/--search` alias, which the dispatcher runs through the identical call.

Both turn into a false negative at the same moment: when someone concludes something from what is
ABSENT. No booking, no reply, no invoice, never heard from them.

The warnings go to stderr so `--json` stays machine-parseable, and these tests pin both halves:
that each fires when a result really is unreliable, and that each stays quiet everywhere else.
**A warning that fired on every call would be trained out within a day**, which is why the search
warning is scoped to an EMPTY unfoldered search rather than to every search, on either route.
"""

from types import SimpleNamespace

from microsoft_cli import cli


def _run(capsys, result, *, group="email", command="list", search=None, **kw):
    args = SimpleNamespace(group=group, command=command, json=True, json_pretty=False, search=search, **kw)
    cli._print_result(args, result)
    cap = capsys.readouterr()
    return cap.out, cap.err


# --- the cap warning -------------------------------------------------------------------------


def test_exactly_at_the_limit_warns(capsys):
    _out, err = _run(capsys, [{"id": i} for i in range(400)], limit=400)
    assert "TRUNCATED" in err
    assert "400" in err


def test_under_the_limit_is_silent(capsys):
    _out, err = _run(capsys, [{"id": i} for i in range(161)], limit=400)
    assert err == ""


# --- the search-scope warning ----------------------------------------------------------------


def test_empty_mailbox_wide_search_warns_about_junk(capsys):
    """The founding case: a query returns nothing and the messages are sitting in Junk."""
    _out, err = _run(capsys, [], command="search", limit=10, folder=None)
    assert "JunkEmail" in err
    assert "DeletedItems" in err


def test_empty_search_scoped_to_a_folder_is_silent(capsys):
    """Asking one folder and getting nothing is a real answer about that folder."""
    _out, err = _run(capsys, [], command="search", limit=10, folder="junk")
    assert err == ""


def test_search_with_results_is_silent(capsys):
    """Only absence gets misread. A non-empty result must not carry the note, or it becomes noise."""
    _out, err = _run(capsys, [{"id": "a"}], command="search", limit=10, folder=None)
    assert err == ""


def test_empty_list_query_warns_because_it_runs_the_same_search(capsys):
    """`email list --query` is not a folder read: the dispatcher sends it down the identical
    `$search` route with folder=None, and it is the spelling agents reach for first, so an empty
    result there hides the same Junk messages."""
    _out, err = _run(capsys, [], command="list", limit=10, folder="inbox", search="someone@x.com")
    assert "JunkEmail" in err
    assert "DeletedItems" in err
    assert "--folder junk" in err


def test_empty_list_query_scoped_to_a_folder_is_silent(capsys):
    """A query narrowed to one folder is a real answer about that folder, on this route too."""
    _out, err = _run(capsys, [], command="list", limit=10, folder="junk", search="someone@x.com")
    assert err == ""


def test_empty_list_without_a_query_stays_silent(capsys):
    """A plain `email list` really does read one folder, so the scope caveat does not apply."""
    _out, err = _run(capsys, [], command="list", limit=10, folder="inbox", search=None)
    assert err == ""


def test_real_parsed_args_from_both_routes_warn(capsys):
    """Built from the actual parser, not a hand-made namespace, so the two routes cannot drift
    apart through a renamed flag or a changed default."""
    parser = cli.build_parser()
    for argv in (
        ["email", "search", "--account", "me@example.com", "--query", "someone@x.com"],
        ["email", "list", "--account", "me@example.com", "--query", "someone@x.com"],
    ):
        cli._print_result(parser.parse_args(argv), [])
        assert "JunkEmail" in capsys.readouterr().err


def test_both_warnings_can_fire_independently(capsys):
    """A full search result warns about the cap and NOT about scope."""
    _out, err = _run(capsys, [{"id": i} for i in range(10)], command="search", limit=10, folder=None)
    assert "TRUNCATED" in err
    assert "JunkEmail" not in err
