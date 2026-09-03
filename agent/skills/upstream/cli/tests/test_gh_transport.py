import json
import subprocess

import pytest
from upstream_cli import cli

from tests.conftest import SENTINEL


def test_gh_env_injects_token_and_repo():
    env = cli.gh_env(SENTINEL)
    assert env["GH_TOKEN"] == SENTINEL
    assert env["GH_REPO"] == "elyxlz/vesta"


def test_gh_api_puts_the_token_in_env_never_argv(fake_gh):
    record, response, _ = fake_gh
    response.write_text(json.dumps({"ok": True}))
    code, out = cli.gh_api(SENTINEL, "repos/elyxlz/vesta/pulls/1")
    seen = json.loads(record.read_text())
    assert code == 0
    assert json.loads(out) == {"ok": True}
    assert seen["env"]["GH_TOKEN"] == SENTINEL
    assert SENTINEL not in " ".join(seen["argv"])
    assert seen["argv"][0] == "api"


def test_gh_api_reports_stderr_when_a_failure_prints_no_body(monkeypatch):
    """A transport or usage failure writes nothing to stdout, so callers would print a bare
    "Error:" unless the cause comes back in the returned text."""
    failed = subprocess.CompletedProcess(["gh"], 1, "", "gh: could not resolve host\n")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: failed)
    assert cli.gh_api(SENTINEL, "repos/elyxlz/vesta/pulls/1") == (1, "gh: could not resolve host\n")


def test_gh_api_keeps_the_api_error_body_when_gh_prints_one(monkeypatch):
    refused = subprocess.CompletedProcess(["gh"], 1, '{"message": "Validation Failed"}', "gh: Validation Failed (HTTP 422)\n")
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **k: refused)
    assert cli.gh_api(SENTINEL, "repos/elyxlz/vesta/pulls") == (1, '{"message": "Validation Failed"}')


def test_a_missing_gh_binary_exits_with_a_message_naming_gh(monkeypatch, capsys):
    def no_such_binary(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "gh")

    monkeypatch.setattr(cli.subprocess, "run", no_such_binary)
    with pytest.raises(SystemExit) as stop:
        cli.gh_api(SENTINEL, "repos/elyxlz/vesta/pulls/1")
    assert stop.value.code == 1
    assert "`gh` is not installed" in capsys.readouterr().err


def test_gh_api_post_sends_fields(fake_gh):
    record, _, _ = fake_gh
    cli.gh_api(SENTINEL, "repos/elyxlz/vesta/issues", method="POST", fields={"title": "t", "body": "b"})
    seen = json.loads(record.read_text())
    assert seen["argv"][:3] == ["api", "-X", "POST"]
    assert "title=t" in seen["argv"] and "body=b" in seen["argv"]
