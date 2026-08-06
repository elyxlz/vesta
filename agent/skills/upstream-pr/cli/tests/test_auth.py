import base64
import os
import subprocess
import sys

import pytest
from upstream_pr_cli import cli

SENTINEL = "ghs_SENTINELtoken1234567890abcdef"
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


def test_main_scrubs_a_leaked_token_and_never_writes_one_to_git_config(repo, monkeypatch):
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "get_installation_token", lambda: SENTINEL)
    monkeypatch.setattr(cli, "ensure_shared_history", lambda base, env: None)
    monkeypatch.setattr(cli, "create_pr", lambda *a, **k: None)
    monkeypatch.setattr(cli, "resolve_agent_identity", lambda: ("tester", "9.9.9"))
    monkeypatch.setattr(sys, "argv", ["upstream-pr", "--title", "t"])

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

    config = (repo / ".git" / "config").read_text()
    assert SENTINEL not in config
    assert "x-access-token" not in config
    # Auth was still delivered, via the push env and not argv where `ps` would see it.
    assert SENTINEL not in " ".join(pushed["cmd"])
    delivered = pushed["env"]["GIT_CONFIG_VALUE_0"].split("Basic ")[1]
    assert base64.b64decode(delivered).decode() == f"x-access-token:{SENTINEL}"


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def _commits(*names):
    return [{"commit": {"author": {"name": name}}} for name in names]


def _stub_get(monkeypatch, response):
    monkeypatch.setattr(cli.requests, "get", lambda *a, **k: response)


# Every agent files through one GitHub App, so a PR's `user.login` is the bot for all of them and
# the commit author is the only ownership signal. These guard the push path, which force-pushes.
def test_push_guard_blocks_a_branch_that_is_only_another_agents(monkeypatch):
    _stub_get(monkeypatch, FakeResponse(_commits("bazella (vesta)", "dory (vesta)")))
    with pytest.raises(SystemExit):
        cli.warn_if_branch_belongs_to_another_agent("tok", "their-branch", "vesta")


def test_push_guard_allows_a_branch_you_already_have_commits_on(monkeypatch):
    _stub_get(monkeypatch, FakeResponse(_commits("bazella (vesta)", "vesta (vesta)")))
    cli.warn_if_branch_belongs_to_another_agent("tok", "shared-branch", "vesta")


def test_push_guard_allows_a_branch_that_does_not_exist_yet(monkeypatch):
    # The normal flow: a brand new branch 404s here, and must not be blocked.
    _stub_get(monkeypatch, FakeResponse({"message": "Not Found"}, status_code=404))
    cli.warn_if_branch_belongs_to_another_agent("tok", "brand-new-branch", "vesta")


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
    monkeypatch.setattr(cli.requests, "get", lambda *a, **k: FakeResponse(prs))
    monkeypatch.setattr(cli, "pr_commit_authors", lambda token, number: authors[number])

    cli.list_my_prs("tok", "vesta", "open", 40)
    out = capsys.readouterr().out
    assert "Opened by you (1)" in out
    assert "#1" in out.split("Opened by you")[1].split("Not yours")[0]
    assert "Not yours, but you have commits on them (1)" in out
    assert "#2  opened by bazella (vesta)" in out
    assert "#3" not in out
