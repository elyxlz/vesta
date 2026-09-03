"""`--mine` classifies every PR of the requested state, so a PR of yours is never outside a window.

Every case runs against a fake repo of known ownership, one GraphQL page per `gh_api` call, so the
right answer is known in advance and a wrong one is visible.
"""

import json

import pytest
from upstream_cli import cli

ME = "tester (vesta)"
OTHER = "someone-else (vesta)"


def _pr_node(number, authors):
    return {
        "number": number,
        "title": f"pr {number}",
        "url": f"https://x/{number}",
        "commits": {"nodes": [{"commit": {"author": {"name": name}}} for name in authors]},
    }


@pytest.fixture
def repo_with(monkeypatch):
    """Route `gh_api` at a fake repo. `authors_per_pr` lists each PR's commit authors in order, newest
    PR first; numbers count down so the newest PR carries the highest, as GitHub orders them. The
    cursor is the offset of the next page. Returns the (path, method, fields) of every call."""

    def build(authors_per_pr, page_size=cli.PR_PAGE_SIZE):
        total = len(authors_per_pr)
        nodes = [_pr_node(total - i, authors) for i, authors in enumerate(authors_per_pr)]
        calls = []

        def fake_gh_api(token, path, *, method="GET", fields=None):
            calls.append((path, method, dict(fields)))
            start = int(fields["cursor"]) if "cursor" in fields else 0
            end = start + page_size
            page = {"pageInfo": {"hasNextPage": end < total, "endCursor": str(end)}, "nodes": nodes[start:end]}
            return 0, json.dumps({"data": {"repository": {"pullRequests": page}}})

        monkeypatch.setattr(cli, "gh_api", fake_gh_api)
        return calls

    return build


def run_listing(capsys, agent="tester", state="open", limit=40):
    cli.list_my_prs("token", agent, state, limit)
    return capsys.readouterr().out


def opened_section(out):
    return out.split("Opened by you")[1].split("Not yours")[0]


def numbers_listed(section):
    return [int(word[1:]) for word in section.split() if word.startswith("#")]


def test_a_pr_three_pages_deep_is_found(repo_with, capsys):
    """Two PRs are the caller's: the newest, and one at position 200 of 250, which only a listing
    that walks every page before classifying can reach."""
    authors = [[OTHER]] * 250
    authors[0] = [ME]
    authors[200] = [ME]
    calls = repo_with(authors)
    out = run_listing(capsys)
    assert sorted(numbers_listed(opened_section(out))) == [50, 250]
    assert f"Checked all 250 open PR(s) as {ME}." in out
    assert len(calls) == 3


def test_pages_follow_the_cursor_and_the_first_request_carries_none(repo_with, capsys):
    calls = repo_with([[OTHER]] * 250)
    run_listing(capsys)
    assert [(path, method) for path, method, _ in calls] == [("graphql", "POST")] * 3
    assert "cursor" not in calls[0][2]
    assert [fields["cursor"] for _, _, fields in calls[1:]] == ["100", "200"]


def test_mine_separates_prs_you_opened_from_prs_you_only_pushed_to(repo_with, capsys):
    """Ownership is the FIRST commit's author; appearing later is a different relationship."""
    repo_with([[ME], [OTHER, ME], [OTHER]])
    out = run_listing(capsys)
    assert "Opened by you (1)" in out
    assert numbers_listed(opened_section(out)) == [3]
    assert "Not yours, but you have commits on them (1)" in out
    assert f"#2  opened by {OTHER}" in out
    assert "#1" not in out


def test_mine_matches_the_full_author_name_never_a_prefix(repo_with, capsys):
    # Agent "test" must not claim PRs authored by "tester (vesta)".
    repo_with([[ME]])
    out = run_listing(capsys, agent="test")
    assert "Opened by you (0)" in out
    assert "you have commits on them" not in out


def test_limit_caps_the_printed_rows_not_the_prs_checked(repo_with, capsys):
    repo_with([[ME]] * 10)
    out = run_listing(capsys, limit=3)
    assert "Checked all 10 open PR(s)" in out
    assert "Opened by you (10)" in out
    assert numbers_listed(opened_section(out)) == [10, 9, 8]
    assert "7 more not printed" in out


@pytest.mark.parametrize(
    ("state", "states"),
    [("open", "[OPEN]"), ("closed", "[CLOSED, MERGED]"), ("all", "[OPEN, CLOSED, MERGED]")],
)
def test_state_selects_the_graphql_state_set(repo_with, capsys, state, states):
    calls = repo_with([])
    out = run_listing(capsys, state=state)
    assert f"states: {states}," in calls[0][2]["query"]
    assert f"Checked all 0 {state} PR(s)" in out


def test_a_failed_query_exits_instead_of_reporting_nothing_of_yours(monkeypatch, capsys):
    monkeypatch.setattr(cli, "gh_api", lambda *a, **k: (1, "gh: HTTP 502"))
    with pytest.raises(SystemExit) as stop:
        cli.list_my_prs("token", "tester", "open", 40)
    assert stop.value.code == 1
    assert "HTTP 502" in capsys.readouterr().err
