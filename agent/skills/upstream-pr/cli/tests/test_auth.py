import base64
import subprocess
import sys

import pytest
from upstream_pr_cli import cli

SENTINEL = "ghs_SENTINELtoken1234567890abcdef"


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


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
