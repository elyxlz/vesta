import os
import stat

import pytest
from upstream_cli import cli

# One owner: the suite asserts this exact token never reaches argv or .git/config, so a second
# copy could drift out of the assertions while they still pass.
SENTINEL = "ghs_SENTINELtoken1234567890abcdef"
AGENT_IDENTITY = ("tester", "9.9.9")


@pytest.fixture
def agent_identity(monkeypatch):
    monkeypatch.setattr(cli, "resolve_agent_identity", lambda: AGENT_IDENTITY)
    return AGENT_IDENTITY


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    """A gh on PATH that records argv + the env it saw, replays a canned response, and exits with
    whatever code the test wrote to the third file."""
    record = tmp_path / "record.json"
    response = tmp_path / "response.json"
    response.write_text("{}")
    exit_code = tmp_path / "exit_code"
    exit_code.write_text("0")
    script = tmp_path / "gh"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        f"rec = {str(record)!r}\n"
        f"resp = {str(response)!r}\n"
        f"code = {str(exit_code)!r}\n"
        "seen = {'argv': sys.argv[1:], 'env': {k: os.environ[k] for k in ('GH_TOKEN', 'GH_REPO') if k in os.environ}}\n"
        "open(rec, 'w').write(json.dumps(seen))\n"
        "sys.stdout.write(open(resp).read())\n"
        "sys.exit(int(open(code).read().strip()))\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setattr(cli, "get_installation_token", lambda: SENTINEL)
    return record, response, exit_code
