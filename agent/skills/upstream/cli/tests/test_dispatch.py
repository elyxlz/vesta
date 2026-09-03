import json

import pytest
from upstream_cli import cli

from tests.conftest import SENTINEL


def run_main(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["upstream", *argv])
    try:
        cli.main()
    except SystemExit as stop:
        return int(stop.code or 0)
    return 0


def test_bare_and_help_forms_print_usage_on_stdout(monkeypatch, capsys):
    """The daemon contract: a command reached for blind answers with usage instead of failing."""
    for argv in ([], ["-h"], ["--help"], ["help"], ["daemon"], ["daemon", "help"]):
        assert run_main(monkeypatch, argv) == 0
        assert "usage" in capsys.readouterr().out.lower()


def test_unknown_verbs_refuse_with_usage(monkeypatch, capsys):
    assert run_main(monkeypatch, ["--title", "x"]) == 2
    assert "usage: upstream gh" in capsys.readouterr().err
    assert run_main(monkeypatch, ["daemon", "bogus"]) == 1
    assert "usage" in capsys.readouterr().err.lower()


def test_daemon_verbs_dispatch_to_the_daemon(monkeypatch, capsys):
    monkeypatch.setattr(cli.daemon, "daemon_cmd", lambda action: print(json.dumps({"verb": action})) or 0)
    assert run_main(monkeypatch, ["daemon", "status"]) == 0
    assert json.loads(capsys.readouterr().out) == {"verb": "status"}


def test_passthrough_forwards_args_untouched_and_propagates_exit(monkeypatch, fake_gh):
    record, _, exit_code = fake_gh
    exit_code.write_text("3")
    code = run_main(monkeypatch, ["gh", "pr", "view", "2116", "--json", "state"])
    assert code == 3
    seen = json.loads(record.read_text())
    assert seen["argv"] == ["pr", "view", "2116", "--json", "state"]
    assert seen["env"]["GH_TOKEN"] == SENTINEL
    assert seen["env"]["GH_REPO"] == "elyxlz/vesta"


def test_issue_create_validates_title_appends_footer(monkeypatch, fake_gh, agent_identity, capsys):
    record, response, _ = fake_gh
    response.write_text(json.dumps({"html_url": "https://github.com/elyxlz/vesta/issues/1"}))

    assert run_main(monkeypatch, ["gh", "issue", "create", "--title", "Bad Title", "--body", "b"]) == 1
    assert "type(scope)" in capsys.readouterr().err

    assert run_main(monkeypatch, ["gh", "issue", "create", "--title", "fix(skills): a real bug", "--body", "b"]) == 0
    seen = json.loads(record.read_text())
    body_field = next(a for a in seen["argv"] if a.startswith("body="))
    assert "Submitted by **tester** on vesta v9.9.9" in body_field


def test_a_bodyless_create_carries_the_footer_alone():
    """One footer owner for PRs and issues, so a bodyless create never opens with a bare rule."""
    assert cli.body_with_attribution("", "tester", "9.9.9") == "---\nSubmitted by **tester** on vesta v9.9.9"
    assert cli.body_with_attribution("why", "tester", "9.9.9") == "why\n\n---\nSubmitted by **tester** on vesta v9.9.9"


def test_create_refuses_unsupported_gh_flags(monkeypatch, capsys):
    code = run_main(monkeypatch, ["gh", "pr", "create", "--title", "fix(a): b", "--body", "x", "--draft"])
    assert code == 2
    err = capsys.readouterr().err
    assert "--draft" in err and "--head" in err


def test_pr_create_takes_head_as_the_gh_spelling_of_branch(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "submit_pr", lambda args: seen.update({"branch": args.branch}))
    assert run_main(monkeypatch, ["gh", "pr", "create", "--title", "fix(a): b", "--head", "feature-x"]) == 0
    assert seen["branch"] == "feature-x"


def test_token_prints_the_installation_token_and_nothing_else(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_installation_token", lambda: SENTINEL)
    assert run_main(monkeypatch, ["token"]) == 0
    printed = capsys.readouterr()
    assert printed.out == f"{SENTINEL}\n"
    assert printed.err == ""


def test_issue_new_is_the_guarded_issue_create(monkeypatch, capsys):
    """gh accepts `new` for `create`, so the alias must not carry an unvalidated title past here."""
    assert run_main(monkeypatch, ["gh", "issue", "new", "--title", "Bad Title", "--body", "b"]) == 1
    assert "type(scope)" in capsys.readouterr().err


def test_pr_new_is_the_guarded_pr_create(monkeypatch, capsys):
    assert run_main(monkeypatch, ["gh", "pr", "new", "--title", "fix(a): b", "--draft"]) == 2
    assert "--draft" in capsys.readouterr().err


def test_a_canonicalized_alias_still_passes_through_when_it_is_not_intercepted(monkeypatch, fake_gh):
    record, _, _ = fake_gh
    run_main(monkeypatch, ["gh", "issue", "ls", "--state", "open"])
    assert json.loads(record.read_text())["argv"] == ["issue", "list", "--state", "open"]


def test_pr_list_without_mine_passes_through(monkeypatch, fake_gh):
    record, _, _ = fake_gh
    run_main(monkeypatch, ["gh", "pr", "list", "--state", "open"])
    assert json.loads(record.read_text())["argv"][0:2] == ["pr", "list"]


@pytest.mark.parametrize("verb", ["list", "ls"])
def test_pr_list_mine_is_intercepted_under_either_spelling(monkeypatch, fake_gh, agent_identity, capsys, verb):
    record, response, _ = fake_gh
    empty_page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}
    response.write_text(json.dumps({"data": {"repository": {"pullRequests": empty_page}}}))
    assert run_main(monkeypatch, ["gh", "pr", verb, "--mine"]) == 0
    assert json.loads(record.read_text())["argv"][0] == "api"
    assert "as tester (vesta)" in capsys.readouterr().out
