"""`upstream poll` turns what changed on this agent's open PRs since the last pass into notifications.

Every case runs against a fake upstream of known state, so the notifications a pass must write are
known in advance: one per new comment, review, or inline comment, one per settled checks verdict, one
per merge or close, and none at all on the first pass, which only records.
"""

import json

import pytest
from upstream_cli import cli

ME = "tester (vesta)"
OTHER = "someone-else (vesta)"
MAINTAINER = "maintainer"


def open_pr(number, author=ME, rollup="PENDING", contexts=()):
    """One node of the watch query. `contexts` are (name, conclusion) pairs; None rollup means no checks ran."""
    nodes = [{"name": name, "conclusion": conclusion} for name, conclusion in contexts]
    status = None if rollup is None else {"state": rollup, "contexts": {"nodes": nodes}}
    return {
        "number": number,
        "title": f"pr {number}",
        "url": f"https://x/{number}",
        "commits": {"nodes": [{"commit": {"author": {"name": author}}}]},
        "head": {"nodes": [{"commit": {"statusCheckRollup": status}}]},
    }


def comment(comment_id, login, body):
    return {"id": comment_id, "user": {"login": login}, "body": body, "html_url": f"https://x/c/{comment_id}"}


def review(review_id, login, body, state):
    return {**comment(review_id, login, body), "state": state}


def inline(comment_id, login, body, path):
    return {**comment(comment_id, login, body), "path": path}


@pytest.fixture
def upstream(monkeypatch):
    """A fake upstream: `open` lists the watch query's nodes, `feeds` maps a REST path (without the
    repo prefix or query) to its items, and `failing` names paths that answer with a transport error."""
    repo = {"open": [], "feeds": {}, "failing": set()}

    def fake_gh_api(token, path, *, method="GET", fields=None):
        rest = path.removeprefix(f"repos/{cli.UPSTREAM_REPO}/").split("?")[0]
        if path in repo["failing"] or rest in repo["failing"]:
            return 1, "gh: HTTP 502"
        if path == "graphql":
            page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": repo["open"]}
            return 0, json.dumps({"data": {"repository": {"pullRequests": page}}})
        return 0, json.dumps(repo["feeds"][rest] if rest in repo["feeds"] else [])

    monkeypatch.setattr(cli, "gh_api", fake_gh_api)
    return repo


@pytest.fixture
def poll(tmp_path):
    """Runs one pass and returns the notifications it wrote, oldest first, each with its file's type."""
    state_path = tmp_path / "upstream-prs.json"
    notif_dir = tmp_path / "notifications"

    def run(agent="tester"):
        cli.poll_prs("token", agent, state_path, notif_dir)
        files = sorted(notif_dir.glob("*.json")) if notif_dir.exists() else []
        written = [json.loads(path.read_text()) for path in files]
        for path in files:
            path.unlink()
        return written

    run.state_path = state_path
    return run


def test_the_first_pass_records_what_it_finds_and_notifies_nothing(upstream, poll):
    upstream["open"] = [open_pr(7, rollup="SUCCESS")]
    upstream["feeds"]["issues/7/comments"] = [comment(1, MAINTAINER, "please fix")]
    assert poll() == []
    state = json.loads(poll.state_path.read_text())
    assert state == {"7": {"title": "pr 7", "url": "https://x/7", "seen": {"comment": 1}, "checks": "green"}}
    # And a second pass over the same upstream is not a first pass: still nothing, because nothing changed.
    assert poll() == []


def test_a_new_comment_arrives_exactly_once_with_the_pr_named(upstream, poll):
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["feeds"]["issues/7/comments"] = [comment(1, MAINTAINER, "reproduce this before replying")]
    [notif] = poll()
    assert notif["source"] == "upstream"
    assert notif["type"] == "pr_comment"
    assert notif["interrupt"] is False
    assert notif["number"] == 7
    assert notif["title"] == "pr 7"
    assert notif["url"] == "https://x/c/1"
    assert notif["author"] == MAINTAINER
    assert notif["message"] == "reproduce this before replying"
    assert poll() == []


def test_the_apps_own_comments_are_never_news(upstream, poll):
    """Every agent comments through the same App login, so those comments are replies, not news."""
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["feeds"]["issues/7/comments"] = [comment(1, cli.BOT_LOGIN, "fixed in abc123")]
    assert poll() == []
    upstream["feeds"]["issues/7/comments"].append(comment(2, MAINTAINER, "thanks"))
    assert [notif["author"] for notif in poll()] == [MAINTAINER]


def test_checks_report_each_settled_verdict_once_and_again_after_a_push(upstream, poll):
    upstream["open"] = [open_pr(7, rollup="PENDING")]
    poll()
    assert poll() == []
    upstream["open"] = [open_pr(7, rollup="FAILURE", contexts=[("guards", "FAILURE"), ("agent", "SUCCESS"), ("web", "CANCELLED")])]
    [red] = poll()
    assert red["type"] == "pr_checks"
    assert red["checks"] == "red"
    assert red["failing"] == "guards, web"
    assert red["message"] == "checks red: guards, web"
    assert red["url"] == "https://x/7"
    assert poll() == []
    # A push resets the rollup; the next settled verdict is news again, even the same colour.
    upstream["open"] = [open_pr(7, rollup="PENDING")]
    assert poll() == []
    upstream["open"] = [open_pr(7, rollup="SUCCESS", contexts=[("guards", "SUCCESS")])]
    [green] = poll()
    assert green["type"] == "pr_checks"
    assert green["checks"] == "green"
    assert green["failing"] == ""
    assert green["message"] == "checks green"


def test_a_pr_with_no_checks_at_all_is_pending(upstream, poll):
    upstream["open"] = [open_pr(7, rollup=None)]
    poll()
    assert poll() == []


def test_reviews_and_inline_comments_are_comments_too(upstream, poll):
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["feeds"]["pulls/7/reviews"] = [
        review(10, MAINTAINER, "", "COMMENTED"),
        review(11, MAINTAINER, "not at this layer", "CHANGES_REQUESTED"),
    ]
    upstream["feeds"]["pulls/7/comments"] = [inline(20, MAINTAINER, "banned accessor", "agent/x.py")]
    notifs = poll()
    assert [notif["type"] for notif in notifs] == ["pr_comment", "pr_comment"]
    assert notifs[0]["review"] == "CHANGES_REQUESTED"
    assert notifs[0]["message"] == "not at this layer"
    assert notifs[1]["path"] == "agent/x.py"
    assert notifs[1]["message"] == "banned accessor"
    assert poll() == []


def test_a_merged_pr_is_reported_once_and_forgotten(upstream, poll):
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["open"] = []
    upstream["feeds"]["pulls/7"] = {"merged": True, "state": "closed", "merged_by": {"login": MAINTAINER}}
    [notif] = poll()
    assert notif["type"] == "pr_merged"
    assert notif["number"] == 7
    assert notif["url"] == "https://x/7"
    assert notif["author"] == MAINTAINER
    assert poll() == []
    assert json.loads(poll.state_path.read_text()) == {}


def test_a_closed_pr_carries_the_comment_that_closed_it(upstream, poll):
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["open"] = []
    upstream["feeds"]["pulls/7"] = {"merged": False, "state": "closed", "merged_by": None}
    upstream["feeds"]["issues/7/comments"] = [comment(1, MAINTAINER, "superseded by #9, which fixes the producer")]
    [notif] = poll()
    assert notif["type"] == "pr_closed"
    assert notif["author"] == MAINTAINER
    assert notif["message"] == "superseded by #9, which fixes the producer"
    assert poll() == []


def test_a_closed_pr_with_no_comment_says_so(upstream, poll):
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["open"] = []
    upstream["feeds"]["pulls/7"] = {"merged": False, "state": "closed", "merged_by": None}
    [notif] = poll()
    assert notif["type"] == "pr_closed"
    assert notif["message"] == "closed without a comment"


def test_only_prs_this_agent_opened_are_watched(upstream, poll):
    upstream["open"] = [open_pr(7, author=OTHER), open_pr(8, author=ME)]
    poll()
    upstream["feeds"]["issues/7/comments"] = [comment(1, MAINTAINER, "not yours")]
    upstream["feeds"]["issues/8/comments"] = [comment(2, MAINTAINER, "yours")]
    assert [notif["number"] for notif in poll()] == [8]


def test_the_full_author_name_is_matched_never_a_prefix(upstream, poll):
    upstream["open"] = [open_pr(8, author=ME)]
    poll(agent="test")
    assert json.loads(poll.state_path.read_text()) == {}


def test_a_feed_that_cannot_be_read_keeps_its_place_for_the_next_pass(upstream, poll, capsys):
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["feeds"]["issues/7/comments"] = [comment(1, MAINTAINER, "still here")]
    upstream["failing"].add("issues/7/comments")
    assert poll() == []
    assert "could not read comments of #7" in capsys.readouterr().err
    upstream["failing"].clear()
    assert [notif["message"] for notif in poll()] == ["still here"]


def test_a_vanished_pr_that_cannot_be_read_back_stays_watched(upstream, poll):
    upstream["open"] = [open_pr(7)]
    poll()
    upstream["open"] = []
    upstream["failing"].add("pulls/7")
    assert poll() == []
    assert "7" in json.loads(poll.state_path.read_text())
    upstream["failing"].clear()
    upstream["feeds"]["pulls/7"] = {"merged": True, "state": "closed", "merged_by": {"login": MAINTAINER}}
    assert [notif["type"] for notif in poll()] == ["pr_merged"]


def test_a_pr_opened_since_the_last_pass_reports_the_conversation_it_already_has(upstream, poll):
    """Only the very first pass seeds silently: a PR that appears later was never seen, so what is
    already on it is news, including a settled checks verdict."""
    upstream["open"] = []
    poll()
    upstream["open"] = [open_pr(9, rollup="SUCCESS")]
    upstream["feeds"]["issues/9/comments"] = [comment(1, MAINTAINER, "looks right")]
    assert sorted(notif["type"] for notif in poll()) == ["pr_checks", "pr_comment"]


def test_a_failed_listing_exits_and_leaves_the_record_alone(upstream, poll):
    upstream["open"] = [open_pr(7)]
    poll()
    before = poll.state_path.read_text()
    upstream["failing"].add("graphql")
    with pytest.raises(SystemExit) as stop:
        poll()
    assert stop.value.code == 1
    assert poll.state_path.read_text() == before
