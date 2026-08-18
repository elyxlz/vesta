import json
import os
import stat

import pytest
from upstream_cli import cli

SENTINEL = "ghs_SENTINELtoken1234567890abcdef"


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    """A gh on PATH that records argv + the env it saw, and replays a canned response."""
    record = tmp_path / "record.json"
    response = tmp_path / "response.json"
    response.write_text("{}")
    script = tmp_path / "gh"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"rec = {str(record)!r}\n"
        f"resp = {str(response)!r}\n"
        "seen = {'argv': sys.argv[1:], 'env': {k: os.environ[k] for k in ('GH_TOKEN', 'GH_REPO') if k in os.environ}}\n"
        "open(rec, 'w').write(json.dumps(seen))\n"
        "sys.stdout.write(open(resp).read())\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(cli, "get_installation_token", lambda: SENTINEL)
    return record, response


def test_gh_env_injects_token_and_repo():
    env = cli.gh_env(SENTINEL)
    assert env["GH_TOKEN"] == SENTINEL
    assert env["GH_REPO"] == "elyxlz/vesta"


def test_gh_api_puts_the_token_in_env_never_argv(fake_gh):
    record, response = fake_gh
    response.write_text(json.dumps({"ok": True}))
    code, out = cli.gh_api(SENTINEL, "repos/elyxlz/vesta/pulls/1")
    seen = json.loads(record.read_text())
    assert code == 0
    assert json.loads(out) == {"ok": True}
    assert seen["env"]["GH_TOKEN"] == SENTINEL
    assert SENTINEL not in " ".join(seen["argv"])
    assert seen["argv"][0] == "api"


def test_gh_api_post_sends_fields(fake_gh):
    record, _ = fake_gh
    cli.gh_api(SENTINEL, "repos/elyxlz/vesta/issues", method="POST", fields={"title": "t", "body": "b"})
    seen = json.loads(record.read_text())
    assert seen["argv"][:3] == ["api", "-X", "POST"]
    assert "title=t" in seen["argv"] and "body=b" in seen["argv"]
