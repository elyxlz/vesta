"""`--mine` must not under-report, because an under-report points the wrong way.

Ownership is the commit author name inside a PR, one API call per PR, so the listing pays page by
page and `--limit` bounds the answer rather than the fetch. A window applied before the ownership
test would leave an agent's older PRs outside it, reading as gone: that says the blockers cleared,
and the next move is a second PR on a file an open PR already touches, which gate 0b forbids.

Every case asserts against a controlled fixture rather than the live repo, so the right answer is
known in advance and a wrong one is visible. `test_a_pr_beyond_a_single_page_window_is_found` is the
regression case: a PR of the caller's sits at position 200 of 250, unreachable by any listing that
fetches one page and truncates it before classifying.
"""

import json

import pytest
from upstream_cli import cli

ME = "tester (vesta)"
OTHER = "someone-else (vesta)"


@pytest.fixture
def repo_with(monkeypatch):
    """Build a fake repo of open PRs and route both API paths at it.

    `owners` is a list of author names, newest first, one per PR. PR numbers count down from
    len(owners) so the newest PR carries the highest number, as GitHub orders them.
    """

    def build(owners, page_size=cli.PAGE_SIZE):
        total = len(owners)
        prs = [{"number": total - i, "title": f"pr {total - i}", "html_url": f"https://x/{total - i}"} for i in range(total)]
        owner_by_number = {pr["number"]: owners[i] for i, pr in enumerate(prs)}
        calls = {"pages": 0, "commit_lookups": 0}

        def fake_gh_api(token, path, **kwargs):
            if "/commits?" in path:
                number = int(path.split("/pulls/")[1].split("/")[0])
                calls["commit_lookups"] += 1
                return 0, json.dumps([{"commit": {"author": {"name": owner_by_number[number]}}}])
            calls["pages"] += 1
            page = int(path.split("&page=")[1]) if "&page=" in path else 1
            start = (page - 1) * page_size
            return 0, json.dumps(prs[start : start + page_size])

        monkeypatch.setattr(cli, "gh_api", fake_gh_api)
        return calls

    return build


def run_listing(capsys, limit=40, scan_limit=cli.SCAN_LIMIT):
    cli.list_my_prs("token", "tester", "open", limit, scan_limit)
    return capsys.readouterr().out


def numbers_listed(out):
    """PR numbers in the 'Opened by you' section only."""
    section = out.split("Opened by you")[1].split("Not yours")[0]
    return [int(word[1:]) for word in section.split() if word.startswith("#")]


def test_a_pr_beyond_a_single_page_window_is_found(repo_with, capsys):
    """THE REGRESSION CASE. Two PRs are the caller's: the newest, which any implementation sees, and
    one at position 200 of 250, which only paginating and classifying as you go can reach."""
    owners = [OTHER] * 250
    owners[0] = ME
    owners[200] = ME
    repo_with(owners)
    out = run_listing(capsys)
    assert sorted(numbers_listed(out)) == sorted([250, 50])
    assert "Examined ALL 250" in out
    assert "complete" in out


def test_complete_scan_says_so(repo_with, capsys):
    """A total and a floor must be distinguishable, so a complete scan claims completeness."""
    repo_with([ME, OTHER, ME])
    out = run_listing(capsys)
    assert "Examined ALL 3" in out
    assert "FLOOR" not in out


def test_fewer_of_mine_than_the_limit_returns_them_all(repo_with, capsys):
    """The control for the limit cases below: when nothing truncates, nothing is announced."""
    owners = [OTHER] * 30
    owners[5] = ME
    owners[17] = ME
    repo_with(owners)
    out = run_listing(capsys, limit=40)
    assert len(numbers_listed(out)) == 2
    assert "Examined ALL 30" in out
    assert "FLOOR" not in out


def test_limit_bounds_my_prs_not_the_fetch(repo_with, capsys):
    """--limit sizes the ANSWER, so it stops the scan once that many of yours are in hand, and the
    result is flagged as a floor because the repo may hold more."""
    repo_with([ME] * 10)
    out = run_listing(capsys, limit=3)
    assert len(numbers_listed(out)) == 3
    assert "FLOOR" in out
    assert "--limit of 3" in out


def test_scan_cap_is_announced_not_silent(repo_with, capsys):
    """A cap that does not announce itself is silent truncation wearing a different number."""
    owners = [OTHER] * 100
    owners[80] = ME
    repo_with(owners)
    out = run_listing(capsys, scan_limit=20)
    assert numbers_listed(out) == []
    assert "FLOOR" in out
    assert "scan cap of 20" in out
    assert "Examined 20" in out


def test_scan_cap_stops_paying_for_lookups(repo_with, capsys):
    """The cap exists to bound cost: one API call per PR examined, so it must actually stop."""
    calls = repo_with([OTHER] * 500)
    run_listing(capsys, scan_limit=25)
    assert calls["commit_lookups"] == 25


def test_commits_by_me_on_someone_elses_pr_are_reported_separately(monkeypatch, capsys):
    """Ownership is the FIRST commit's author; appearing later is a different relationship."""

    def fake_gh_api(token, path, **kwargs):
        if "/commits?" in path:
            return 0, json.dumps([{"commit": {"author": {"name": OTHER}}}, {"commit": {"author": {"name": ME}}}])
        page = int(path.split("&page=")[1]) if "&page=" in path else 1
        return 0, json.dumps([{"number": 7, "title": "t", "html_url": "u"}] if page == 1 else [])

    monkeypatch.setattr(cli, "gh_api", fake_gh_api)
    out = run_listing(capsys)
    assert numbers_listed(out) == []
    assert "you have commits on them (1)" in out
