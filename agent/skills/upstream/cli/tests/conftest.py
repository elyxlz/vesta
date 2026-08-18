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
