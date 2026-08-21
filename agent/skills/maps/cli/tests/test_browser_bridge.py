import json
import stat
from pathlib import Path

import pytest

from gmaps_cli import browser_bridge
from gmaps_cli.browser_bridge import BrowserUnavailableError, SignedOutError

_SHIM = """#!/usr/bin/env python3
import json, os, sys
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "evaluate":
    sys.stdout.write(os.environ["FAKE_EVAL_OUT"])
else:
    sys.stdout.write("{}")
"""


def _install_shim(tmp_path: Path, eval_out: str, monkeypatch) -> None:
    shim = tmp_path / "browser"
    shim.write_text(_SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MAPS_BROWSER_BIN", str(shim))
    monkeypatch.setenv("FAKE_EVAL_OUT", eval_out)


def test_entitylist_get_returns_parsed_json(tmp_path, monkeypatch):
    envelope = json.dumps({"signed_in": True, "status": 200, "body": ")]}'\n[[1,2,3]]"})
    _install_shim(tmp_path, envelope, monkeypatch)
    result = browser_bridge.entitylist_get("list", "!1e3")
    assert result == [[1, 2, 3]]


def test_entitylist_get_raises_signed_out(tmp_path, monkeypatch):
    envelope = json.dumps({"signed_in": False, "status": 302, "body": ""})
    _install_shim(tmp_path, envelope, monkeypatch)
    with pytest.raises(SignedOutError):
        browser_bridge.entitylist_get("list", "!1e3")


def test_missing_browser_binary_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPS_BROWSER_BIN", str(tmp_path / "does-not-exist"))
    with pytest.raises(BrowserUnavailableError):
        browser_bridge.entitylist_get("list", "!1e3")
