import base64
import json
import os
import subprocess
import sys

import pytest
from upstream_cli import cli

from tests.conftest import AGENT_IDENTITY, SENTINEL

# The host's own git config must not reach these repos: a user-level commit.gpgSign would sign
# every fixture commit, and fail wherever no key is available.
HERMETIC_GIT = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=os.environ | HERMETIC_GIT)


@pytest.fixture
def repo(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "a@b.c")
    _git(work, "config", "user.name", "init")
    (work / "f.txt").write_text("hi")
    _git(work, "add", "f.txt")
    _git(work, "commit", "-qm", "init")
    # Simulate a box leaked by the old version: a live token already in .git/config.
    _git(work, "remote", "add", "upstream", f"https://x-access-token:{SENTINEL}@github.com/elyxlz/vesta.git")
    return work


def test_git_auth_env_keeps_the_token_out_of_the_key_and_only_base64_in_the_value():
    env = cli.git_auth_env(SENTINEL)
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    header = env["GIT_CONFIG_VALUE_0"]
    assert SENTINEL not in header
    assert base64.b64decode(header.split("Basic ")[1]).decode() == f"x-access-token:{SENTINEL}"


def _run_main_to_push(repo, monkeypatch, argv):
    """Drive `main()` up to the push, swallowing it. Returns what the push saw and every call the
    ownership guard took, so a test can assert on either without restubbing main()'s whole surface."""
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "get_installation_token", lambda: SENTINEL)
    monkeypatch.setattr(cli, "ensure_shared_history", lambda base, env: None)
    monkeypatch.setattr(cli, "create_pr", lambda *a, **k: None)
    monkeypatch.setattr(cli, "resolve_agent_identity", lambda: AGENT_IDENTITY)
    # The ownership guard has its own tests below; unstubbed it would dial the real remote.
    guard_calls = []
    monkeypatch.setattr(cli, "warn_if_branch_belongs_to_another_agent", lambda *a: guard_calls.append(a))
    monkeypatch.setattr(sys, "argv", argv)

    pushed = {}
    real_run = cli.run

    def fake_run(cmd, env=None):
        if cmd[:2] == ["git", "push"]:
            pushed["cmd"] = cmd
            pushed["env"] = env
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, env=env)

    monkeypatch.setattr(cli, "run", fake_run)
    cli.main()
    return pushed, guard_calls


def test_main_scrubs_a_leaked_token_and_never_writes_one_to_git_config(repo, monkeypatch):
    pushed, _ = _run_main_to_push(repo, monkeypatch, ["upstream", "gh", "pr", "create", "--title", "fix(test): t"])

    config = (repo / ".git" / "config").read_text()
    assert SENTINEL not in config
    assert "x-access-token" not in config
    # Auth was still delivered, via the push env and not argv where `ps` would see it.
    assert SENTINEL not in " ".join(pushed["cmd"])
    delivered = pushed["env"]["GIT_CONFIG_VALUE_0"].split("Basic ")[1]
    assert base64.b64decode(delivered).decode() == f"x-access-token:{SENTINEL}"


def _commits(*names):
    return [{"commit": {"author": {"name": name}}} for name in names]


def _stub_gh_api(monkeypatch, payload, code=0):
    monkeypatch.setattr(cli, "gh_api", lambda *a, **k: (code, json.dumps(payload)))


def _stub_authors(monkeypatch, authors):
    monkeypatch.setattr(cli, "branch_authors_ahead_of_base", lambda branch, base, env: authors)


# Every agent files through one GitHub App, so a PR's `user.login` is the bot for all of them and
# the commit author is the only ownership signal. These guard the push path, which force-pushes.
@pytest.mark.parametrize(
    "authors",
    [
        {"bazella (vesta)", "dory (vesta)"},  # only other agents' commits
        {"Emilio Pascarelli"},  # a human's branch under the same name
        {"vestal (vesta)"},  # a similar name is still not you
    ],
)
def test_push_guard_blocks_a_branch_with_no_commit_of_yours(monkeypatch, authors):
    _stub_authors(monkeypatch, authors)
    with pytest.raises(SystemExit):
        cli.warn_if_branch_belongs_to_another_agent("their-branch", "master", "vesta", {})


@pytest.mark.parametrize(
    "authors",
    [
        {"bazella (vesta)", "vesta (vesta)"},  # you have commits on it
        {"vesta (vesta)"},
        set(),  # exists but adds nothing on base: no work to lose
        None,  # no such remote branch yet: the normal new-branch flow
    ],
)
def test_push_guard_allows_a_branch_that_is_yours_or_holds_no_work(monkeypatch, authors):
    _stub_authors(monkeypatch, authors)
    cli.warn_if_branch_belongs_to_another_agent("some-branch", "master", "vesta", {})


def _stub_git(monkeypatch, ls_remote_rc=0, fetch_rc=0, log_out="dory (vesta)\n"):
    calls = []

    def fake_run(cmd, env=None):
        calls.append(cmd)
        if cmd[:2] == ["git", "ls-remote"]:
            return subprocess.CompletedProcess(cmd, ls_remote_rc, "", "")
        if cmd[:2] == ["git", "fetch"]:
            return subprocess.CompletedProcess(cmd, fetch_rc, "", "")
        if cmd[:2] == ["git", "log"]:
            return subprocess.CompletedProcess(cmd, 0, log_out, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(cli, "run", fake_run)
    return calls


def test_a_missing_remote_branch_is_the_only_silent_pass(monkeypatch):
    # ls-remote --exit-code exits 2 exactly when the remote says the ref does not exist.
    calls = _stub_git(monkeypatch, ls_remote_rc=2)
    assert cli.branch_authors_ahead_of_base("brand-new", "master", {}) is None
    assert not any(c[:2] == ["git", "fetch"] for c in calls)


def test_an_unreachable_remote_refuses_instead_of_passing(monkeypatch):
    """An auth failure or outage exits nonzero-but-not-2, and must not read as "no such branch":
    ownership is unverifiable and the push about to happen is a force push."""
    _stub_git(monkeypatch, ls_remote_rc=128)
    with pytest.raises(SystemExit):
        cli.branch_authors_ahead_of_base("b", "master", {})


def test_a_failed_fetch_of_an_existing_branch_refuses_and_cleans_up(monkeypatch):
    calls = _stub_git(monkeypatch, fetch_rc=1)
    with pytest.raises(SystemExit):
        cli.branch_authors_ahead_of_base("b", "master", {})
    assert ["git", "update-ref", "-d", cli.GUARD_BRANCH_REF] in calls
    assert ["git", "update-ref", "-d", cli.GUARD_BASE_REF] in calls


def test_guard_reads_only_the_commits_the_branch_adds(monkeypatch):
    """Master ancestry must not leak in: a branch one commit ahead is judged on that one commit."""
    calls = _stub_git(monkeypatch)
    assert cli.branch_authors_ahead_of_base("theirs", "master", {}) == {"dory (vesta)"}
    log_cmd = next(c for c in calls if c[:2] == ["git", "log"])
    assert log_cmd[-1] == f"{cli.GUARD_BASE_REF}..{cli.GUARD_BRANCH_REF}"
    assert ["git", "update-ref", "-d", cli.GUARD_BRANCH_REF] in calls
    assert ["git", "update-ref", "-d", cli.GUARD_BASE_REF] in calls


@pytest.fixture
def remote_with_their_branch(tmp_path):
    """A real local 'upstream' whose branch `theirs` carries one commit by another agent."""
    src = tmp_path / "src"
    src.mkdir()
    _git(src, "init", "-q", "-b", "master")
    _git(src, "config", "user.email", "a@b.c")
    _git(src, "config", "user.name", "init")
    (src / "f").write_text("1")
    _git(src, "add", "f")
    _git(src, "commit", "-qm", "base")
    _git(src, "checkout", "-qb", "theirs")
    (src / "f").write_text("2")
    _git(src, "commit", "-qam", "their work", "--author=dory (vesta) <d@vesta.noreply>")
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _git(consumer, "init", "-q")
    _git(consumer, "remote", "add", "upstream", str(src))
    return consumer


def test_guard_reads_ownership_from_a_real_local_remote(remote_with_their_branch, monkeypatch):
    monkeypatch.chdir(remote_with_their_branch)
    env = os.environ | HERMETIC_GIT
    assert cli.branch_authors_ahead_of_base("theirs", "master", env) == {"dory (vesta)"}
    assert cli.branch_authors_ahead_of_base("no-such-branch", "master", env) is None
    leftover = subprocess.run(["git", "for-each-ref", "refs/vesta-guard"], capture_output=True, text=True, env=env, check=True)
    assert leftover.stdout == ""


def test_push_runs_the_ownership_guard(repo, monkeypatch):
    _, guard_calls = _run_main_to_push(repo, monkeypatch, ["upstream", "gh", "pr", "create", "--title", "fix(test): t"])
    assert len(guard_calls) == 1


def test_adopt_skips_the_ownership_guard(repo, monkeypatch):
    argv = ["upstream", "gh", "pr", "create", "--title", "fix(test): t", "--adopt"]
    _, guard_calls = _run_main_to_push(repo, monkeypatch, argv)
    assert guard_calls == []


def test_pr_commit_authors_reads_the_first_commit_as_the_opener(monkeypatch):
    _stub_gh_api(monkeypatch, _commits("dory (vesta)", "vesta (vesta)"))
    assert cli.pr_commit_authors("tok", 7) == ("dory (vesta)", {"dory (vesta)", "vesta (vesta)"})


def test_pr_commit_authors_reports_unknown_on_an_api_error(monkeypatch):
    _stub_gh_api(monkeypatch, [], code=1)
    assert cli.pr_commit_authors("tok", 7) == (None, set())


def test_agent_identity_rejects_a_blank_agent_name(monkeypatch):
    monkeypatch.setenv("AGENT_NAME", "  ")
    with pytest.raises(SystemExit):
        cli.resolve_agent_identity()


def test_mine_separates_prs_you_opened_from_prs_you_only_pushed_to(monkeypatch, capsys):
    prs = [
        {"number": 1, "title": "yours", "html_url": "u1"},
        {"number": 2, "title": "theirs, you pushed", "html_url": "u2"},
        {"number": 3, "title": "theirs", "html_url": "u3"},
    ]
    authors = {
        1: ("vesta (vesta)", {"vesta (vesta)"}),
        2: ("bazella (vesta)", {"bazella (vesta)", "vesta (vesta)"}),
        3: ("dory (vesta)", {"dory (vesta)"}),
    }
    _stub_gh_api(monkeypatch, prs)
    monkeypatch.setattr(cli, "pr_commit_authors", lambda token, number: authors[number])

    cli.list_my_prs("tok", "vesta", "open", 40)
    out = capsys.readouterr().out
    assert "Opened by you (1)" in out
    assert "#1" in out.split("Opened by you")[1].split("Not yours")[0]
    assert "Not yours, but you have commits on them (1)" in out
    assert "#2  opened by bazella (vesta)" in out
    assert "#3" not in out


def test_mine_matches_the_full_author_name_never_a_prefix(monkeypatch, capsys):
    # Agent "dor" must not claim PRs authored by "dory (vesta)".
    prs = [{"number": 1, "title": "t", "html_url": "u"}]
    _stub_gh_api(monkeypatch, prs)
    monkeypatch.setattr(cli, "pr_commit_authors", lambda token, number: ("dory (vesta)", {"dory (vesta)"}))

    cli.list_my_prs("tok", "dor", "open", 40)
    out = capsys.readouterr().out
    assert "Opened by you (0)" in out
    assert "you have commits on them" not in out


def test_mine_respects_the_limit_and_surfaces_unreadable_prs(monkeypatch, capsys):
    prs = [{"number": n, "title": f"t{n}", "html_url": f"u{n}"} for n in (1, 2, 3)]
    checked = []

    def unreadable_authors(token, number):
        checked.append(number)
        return (None, set())

    _stub_gh_api(monkeypatch, prs)
    monkeypatch.setattr(cli, "pr_commit_authors", unreadable_authors)

    cli.list_my_prs("tok", "vesta", "open", 2)
    out = capsys.readouterr().out
    assert checked == [1, 2]
    assert "Could not read commit authors for 2 PR(s)" in out


def test_mine_passes_the_requested_state_to_the_api(monkeypatch, capsys):
    seen = []

    def fake_gh_api(token, path, **kwargs):
        seen.append(path)
        return 0, "[]"

    monkeypatch.setattr(cli, "gh_api", fake_gh_api)
    cli.list_my_prs("tok", "vesta", "all", 40)
    assert "state=all" in seen[0]
