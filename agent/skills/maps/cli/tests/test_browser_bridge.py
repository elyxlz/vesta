import json
import stat
from pathlib import Path

import pytest
from gmaps_cli import browser_bridge
from gmaps_cli.browser_bridge import BrowserUnavailableError, SignedOutError, WriteRejectedError, _Envelope

# Reads the program on stdin and answers one browser.result.v1 envelope. `SHIM_LOG` (when set)
# records argv and whether DISPLAY leaked into the shim's environment, for the callers below to
# assert on. `FAKE_ERROR_CODE`/`FAKE_ERROR_MESSAGE` (when set) answer a failing envelope on
# stderr with exit 1; otherwise `FAKE_EVAL_OUT` answers a successful one on stdout.
_SHIM = (
    "#!/usr/bin/env python3\n"
    "import json, os, sys\n"
    "code = sys.stdin.read()\n"
    "if 'SHIM_LOG' in os.environ:\n"
    "    with open(os.environ['SHIM_LOG'], 'w') as f:\n"
    "        json.dump({'argv': sys.argv[1:], 'display': 'DISPLAY' in os.environ, 'code': code}, f)\n"
    "if 'FAKE_ERROR_CODE' in os.environ:\n"
    "    envelope = {'schema': 'browser.result.v1', 'ok': False, 'error': {\n"
    "        'code': os.environ['FAKE_ERROR_CODE'], 'phase': 'launch',\n"
    "        'message': os.environ['FAKE_ERROR_MESSAGE'], 'retryable': True,\n"
    "        'suggested_action': 'run: browser daemon start'}}\n"
    "    sys.stderr.write(json.dumps(envelope))\n"
    "    sys.exit(1)\n"
    "envelope = {'schema': 'browser.result.v1', 'ok': True,\n"
    "    'output': {'stdout': os.environ['FAKE_EVAL_OUT'], 'stderr': '', 'exit_code': 0, 'duration_ms': 1}}\n"
    "sys.stdout.write(json.dumps(envelope))\n"
)


def _install_shim(tmp_path: Path, eval_out: str, monkeypatch) -> None:
    shim = tmp_path / "browser"
    shim.write_text(_SHIM)
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


def test_entitylist_get_uses_exec_default_session_with_no_display(tmp_path, monkeypatch):
    envelope = json.dumps({"signed_in": True, "status": 200, "body": ")]}'\n[[1]]"})
    _install_shim(tmp_path, envelope, monkeypatch)
    log = tmp_path / "shim.json"
    monkeypatch.setenv("SHIM_LOG", str(log))
    monkeypatch.delenv("DISPLAY", raising=False)
    browser_bridge.entitylist_get("list", "!1e3")
    logged = json.loads(log.read_text())
    assert logged["argv"] == ["exec", "--session", "default"]
    assert logged["display"] is False


def test_missing_browser_binary_raises_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("MAPS_BROWSER_BIN", str(tmp_path / "does-not-exist"))
    with pytest.raises(BrowserUnavailableError):
        browser_bridge.entitylist_get("list", "!1e3")


def test_daemon_down_error_names_browser_daemon_start(tmp_path, monkeypatch):
    shim = tmp_path / "browser"
    shim.write_text(_SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MAPS_BROWSER_BIN", str(shim))
    monkeypatch.setenv("FAKE_ERROR_CODE", "daemon_down")
    monkeypatch.setenv("FAKE_ERROR_MESSAGE", "browser daemon not reachable at /run/browser.sock")
    with pytest.raises(BrowserUnavailableError) as exc_info:
        browser_bridge.entitylist_get("list", "!1e3")
    assert "start the browser daemon" in str(exc_info.value)


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
