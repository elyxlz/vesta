import json
import re
import stat
from pathlib import Path

import pytest
from gmaps_cli import browser_bridge
from gmaps_cli.browser_bridge import BrowserUnavailableError, SignedOutError, WriteRejectedError, _Envelope
from gmaps_cli.pb import SESSION_TOKEN_RE

# Reads the program on stdin and answers one browser.result.v1 envelope. `SHIM_LOG` (when set)
# records argv and whether DISPLAY leaked into the shim's environment, for the callers below to
# assert on. `FAKE_ERROR_CODE`/`FAKE_ERROR_MESSAGE` (when set) answer a failing envelope on
# stderr with exit 1; otherwise `FAKE_EVAL_OUT` answers a successful one on stdout, carrying
# `FAKE_WARNINGS` as the envelope's warnings.
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
    "        'suggested_action': 'run: browser daemon start'},\n"
    "        'warnings': []}\n"
    "    sys.stderr.write(json.dumps(envelope))\n"
    "    sys.exit(1)\n"
    "envelope = {'schema': 'browser.result.v1', 'ok': True,\n"
    "    'output': {'stdout': os.environ['FAKE_EVAL_OUT'], 'stderr': '', 'exit_code': 0, 'duration_ms': 1},\n"
    "    'warnings': json.loads(os.environ['FAKE_WARNINGS']) if 'FAKE_WARNINGS' in os.environ else []}\n"
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
    monkeypatch.setattr(browser_bridge, "_page_tokens", lambda: ("SESS", ["BAD:1", "ALSOBAD:2"]))
    monkeypatch.setattr(browser_bridge, "_fetch", lambda op, pb: _Envelope(signed_in=True, status=400, body=""))
    with pytest.raises(WriteRejectedError):
        browser_bridge.entitylist_write("create", lambda session, consistency: f"!9s{consistency}")


def test_entitylist_write_signed_out_raises(monkeypatch):
    def signed_out() -> tuple[str, list[str]]:
        raise SignedOutError("no session token")

    monkeypatch.setattr(browser_bridge, "_page_tokens", signed_out)
    with pytest.raises(SignedOutError):
        browser_bridge.entitylist_write("create", lambda session, consistency: "!x")


def test_consistency_pool_dedups_and_orders():
    html = "x AMAbHIaaa:1 y AMAbHIbbb:2 z AMAbHIaaa:1 w"
    found = list(dict.fromkeys(browser_bridge._CONSISTENCY_RE.findall(html)))
    assert found == ["AMAbHIaaa:1", "AMAbHIbbb:2"]


def test_truncated_output_raises_instead_of_reaching_the_parser(tmp_path, monkeypatch):
    _install_shim(tmp_path, "{}", monkeypatch)
    monkeypatch.setenv("FAKE_WARNINGS", json.dumps(["output_truncated"]))
    with pytest.raises(BrowserUnavailableError, match="truncated"):
        browser_bridge.entitylist_get("list", "!1e3")


def test_page_tokens_reads_the_payload_the_in_page_program_prints(tmp_path, monkeypatch):
    _install_shim(tmp_path, json.dumps({"session_token": "SESS", "pool": ["AMAbHIaaa:1", "AMAbHIbbb:2"]}), monkeypatch)
    assert browser_bridge._page_tokens() == ("SESS", ["AMAbHIaaa:1", "AMAbHIbbb:2"])


@pytest.mark.parametrize("payload", [{"session_token": "", "pool": ["AMAbHIaaa:1"]}, {"session_token": "SESS", "pool": []}])
def test_page_tokens_signed_out_when_either_half_is_empty(payload, tmp_path, monkeypatch):
    _install_shim(tmp_path, json.dumps(payload), monkeypatch)
    with pytest.raises(SignedOutError):
        browser_bridge._page_tokens()


def test_page_tokens_program_carries_the_tab_setup(tmp_path, monkeypatch):
    _install_shim(tmp_path, json.dumps({"session_token": "SESS", "pool": ["AMAbHIaaa:1"]}), monkeypatch)
    log = tmp_path / "shim.json"
    monkeypatch.setenv("SHIM_LOG", str(log))
    browser_bridge._page_tokens()
    code = json.loads(log.read_text())["code"]
    assert "list_tabs()" in code and browser_bridge._TOKEN_PAGE in code


def test_in_page_regexes_agree_with_the_python_rule_on_a_sample():
    """The two patterns the in-page program carries are the Python owners', embedded unchanged."""
    sample = "x AMAbHIaaa:1 y AMAbHIbbb:2 z AMAbHIaaa:1 w"
    embedded_consistency = re.compile(_js_regex(browser_bridge._TOKENS_JS, "text.match(/", "/g)"))
    assert list(dict.fromkeys(embedded_consistency.findall(sample))) == ["AMAbHIaaa:1", "AMAbHIbbb:2"]
    quoted = '["a","fhuGasW6Jv6bkdUPruq4mQE",3]'
    embedded_token = re.compile(_js_regex(browser_bridge._TOKENS_JS, "JSON.stringify(meta).match(/", "/)"))
    assert embedded_token.search(quoted).group(1) == SESSION_TOKEN_RE.search(quoted).group(1)


def _js_regex(program: str, opener: str, closer: str) -> str:
    """The regex source the in-page program carries between `opener` and the following `closer`."""
    start = program.index(opener) + len(opener)
    return program[start : program.index(closer, start)]
