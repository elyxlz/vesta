import json
import stat
from pathlib import Path

import pytest
from gmaps_cli import browser_bridge
from gmaps_cli.browser_bridge import BrowserUnavailableError, SignedOutError, WriteRejectedError, _Envelope

_READ_SHIM = (
    "#!/usr/bin/env python3\n"
    "import os, sys\n"
    "cmd = sys.argv[1] if len(sys.argv) > 1 else ''\n"
    "sys.stdout.write(os.environ['FAKE_EVAL_OUT'] if cmd == 'evaluate' else '{}')\n"
)


def _install_shim(tmp_path: Path, eval_out: str, monkeypatch) -> None:
    shim = tmp_path / "browser"
    shim.write_text(_READ_SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MAPS_BROWSER_BIN", str(shim))
    monkeypatch.setenv("FAKE_EVAL_OUT", eval_out)


def test_entitylist_get_returns_parsed_json(tmp_path, monkeypatch):
    envelope = json.dumps({"signed_in": True, "status": 200, "body": ")]}'\n[[1,2,3]]"})
    _install_shim(tmp_path, envelope, monkeypatch)
    assert browser_bridge.entitylist_get("list", "!1e3") == [[1, 2, 3]]


def test_entitylist_get_raises_signed_out(tmp_path, monkeypatch):
    envelope = json.dumps({"signed_in": False, "status": 302, "body": ""})
    _install_shim(tmp_path, envelope, monkeypatch)
    with pytest.raises(SignedOutError):
        browser_bridge.entitylist_get("list", "!1e3")


def test_missing_browser_binary_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPS_BROWSER_BIN", str(tmp_path / "does-not-exist"))
    with pytest.raises(BrowserUnavailableError):
        browser_bridge.entitylist_get("list", "!1e3")


def test_entitylist_write_tries_pool_until_accepted(monkeypatch):
    monkeypatch.setattr(browser_bridge, "_ensure_tab", lambda: None)
    monkeypatch.setattr(browser_bridge, "_page_tokens", lambda: ("SESS", ["BAD:1", "GOOD:2"]))
    tried: list[str] = []

    def fake_fetch(op: str, pb: str) -> _Envelope:
        tried.append(pb)
        status = 200 if "GOOD" in pb else 400
        return _Envelope(signed_in=True, status=status, body=')]}\'\n[[["NEWID",1]]]')

    monkeypatch.setattr(browser_bridge, "_fetch", fake_fetch)
    result = browser_bridge.entitylist_write("create", lambda session, consistency: f"!1s{session}!9s{consistency}")
    assert result == [[["NEWID", 1]]]
    assert tried == ["!1sSESS!9sBAD:1", "!1sSESS!9sGOOD:2"]  # bad first, then the accepted one


def test_entitylist_write_all_rejected_raises(monkeypatch):
    monkeypatch.setattr(browser_bridge, "_ensure_tab", lambda: None)
    monkeypatch.setattr(browser_bridge, "_page_tokens", lambda: ("SESS", ["BAD:1", "ALSOBAD:2"]))
    monkeypatch.setattr(browser_bridge, "_fetch", lambda op, pb: _Envelope(signed_in=True, status=400, body=""))
    with pytest.raises(WriteRejectedError):
        browser_bridge.entitylist_write("create", lambda session, consistency: f"!9s{consistency}")


def test_entitylist_write_signed_out_raises(monkeypatch):
    monkeypatch.setattr(browser_bridge, "_ensure_tab", lambda: None)

    def signed_out() -> tuple[str, list[str]]:
        raise SignedOutError("no session token")

    monkeypatch.setattr(browser_bridge, "_page_tokens", signed_out)
    with pytest.raises(SignedOutError):
        browser_bridge.entitylist_write("create", lambda session, consistency: "!x")


def test_consistency_pool_dedups_and_orders():
    html = "x AMAbHIaaa:1 y AMAbHIbbb:2 z AMAbHIaaa:1 w"
    found = list(dict.fromkeys(browser_bridge._CONSISTENCY_RE.findall(html)))
    assert found == ["AMAbHIaaa:1", "AMAbHIbbb:2"]
