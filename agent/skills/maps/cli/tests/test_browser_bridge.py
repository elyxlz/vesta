import json
import re
import stat
from pathlib import Path

import pytest
from gmaps_cli import browser_bridge
from gmaps_cli.browser_bridge import BrowserUnavailableError, SignedOutError, WriteRejectedError
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
    _install_shim(tmp_path, "", monkeypatch)
    monkeypatch.setenv("FAKE_ERROR_CODE", "daemon_down")
    monkeypatch.setenv("FAKE_ERROR_MESSAGE", "browser daemon not reachable at /run/browser.sock")
    with pytest.raises(BrowserUnavailableError) as exc_info:
        browser_bridge.entitylist_get("list", "!1e3")
    assert "start the browser daemon" in str(exc_info.value)


def test_entitylist_write_is_one_program_that_tries_the_pool_in_the_page(tmp_path, monkeypatch):
    """One CLI spawn per write: the token read and every pooled attempt run inside the exec'd program."""
    envelope = json.dumps({"signed_in": True, "status": 200, "body": ')]}\'\n[[["NEWID",1]]]'})
    _install_shim(tmp_path, envelope, monkeypatch)
    log = tmp_path / "shim.json"
    monkeypatch.setenv("SHIM_LOG", str(log))
    result = browser_bridge.entitylist_write("create", lambda session, consistency: f"!1s{session}!9s{consistency}")
    assert result == [[["NEWID", 1]]]
    code = json.loads(log.read_text())["code"]
    assert code.count("js(") == 2 and browser_bridge._TOKEN_PAGE in code
    assert "'!1s__SESSION__!9s__CONSISTENCY__'" in code and "for consistency in pool" in code
    assert 'envelope["status"] == 200' in code and "/maps/preview/entitylist/create?" in code


def test_entitylist_write_all_rejected_raises(tmp_path, monkeypatch):
    _install_shim(tmp_path, json.dumps({"signed_in": True, "status": 400, "body": ""}), monkeypatch)
    with pytest.raises(WriteRejectedError):
        browser_bridge.entitylist_write("create", lambda session, consistency: f"!9s{consistency}")


def test_entitylist_write_signed_out_raises(tmp_path, monkeypatch):
    """A page with no tokens, or a fetch that hit the sign-in wall, both print a signed-out envelope."""
    _install_shim(tmp_path, json.dumps({"signed_in": False, "status": 0, "body": ""}), monkeypatch)
    with pytest.raises(SignedOutError):
        browser_bridge.entitylist_write("create", lambda session, consistency: "!x")


def test_consistency_regex_finds_every_pooled_token_in_order():
    html = "x AMAbHIaaa:1 y AMAbHIbbb:2 z AMAbHIaaa:1 w"
    assert browser_bridge._CONSISTENCY_RE.findall(html) == ["AMAbHIaaa:1", "AMAbHIbbb:2", "AMAbHIaaa:1"]


def test_truncated_output_raises_instead_of_reaching_the_parser(tmp_path, monkeypatch):
    _install_shim(tmp_path, "{}", monkeypatch)
    monkeypatch.setenv("FAKE_WARNINGS", json.dumps(["output_truncated"]))
    with pytest.raises(BrowserUnavailableError, match="truncated"):
        browser_bridge.entitylist_get("list", "!1e3")


@pytest.mark.parametrize(
    ("tokens", "fetched"),
    [
        ({"session_token": "SESS", "pool": ["BAD:1", "GOOD:2"]}, ["!1sSESS!9sBAD:1", "!1sSESS!9sGOOD:2"]),
        ({"session_token": "", "pool": ["AMAbHIaaa:1"]}, []),
        ({"session_token": "SESS", "pool": []}, []),
    ],
)
def test_write_program_fetches_once_per_pooled_token_until_accepted(tokens, fetched):
    """The program run under a `js` that answers the token read first, then one fetch per attempt:
    a bad token is a 400 and the loop goes on, the accepted one ends it, and a page with either
    half of its tokens missing prints a signed-out envelope with no fetch at all."""
    program = browser_bridge.write_program("create", lambda session, consistency: f"!1s{session}!9s{consistency}")
    pbs: list[str] = []
    printed: list[str] = []

    def fake_js(expression: str) -> object:
        if expression == browser_bridge._TOKENS_JS:
            return tokens
        pb = expression.split("pb=", 1)[1].split('"', 1)[0]
        pbs.append(pb)
        return {"signed_in": True, "status": 200 if "GOOD" in pb else 400, "body": ""}

    exec(program.replace(browser_bridge._TAB_PROGRAM, ""), {"js": fake_js, "print": printed.append})
    assert pbs == fetched
    assert json.loads(printed[0])["signed_in"] is (tokens["session_token"] != "" and tokens["pool"] != [])


def test_write_program_carries_the_tab_setup(tmp_path, monkeypatch):
    _install_shim(tmp_path, json.dumps({"signed_in": True, "status": 200, "body": "[]"}), monkeypatch)
    log = tmp_path / "shim.json"
    monkeypatch.setenv("SHIM_LOG", str(log))
    browser_bridge.entitylist_write("create", lambda session, consistency: "!x")
    code = json.loads(log.read_text())["code"]
    assert "list_tabs()" in code and browser_bridge._TOKEN_PAGE in code


def test_in_page_regexes_agree_with_the_python_rule_on_a_sample():
    """The two patterns the in-page program carries are the Python owners', embedded unchanged."""
    sample = "x AMAbHIaaa:1 y AMAbHIbbb:2 z AMAbHIaaa:1 w"
    embedded_consistency = re.compile(_js_regex(browser_bridge._TOKENS_JS, "text.match(/", "/g)"))
    assert embedded_consistency.findall(sample) == browser_bridge._CONSISTENCY_RE.findall(sample)
    quoted = '["a","fhuGasW6Jv6bkdUPruq4mQE",3]'
    embedded_token = re.compile(_js_regex(browser_bridge._TOKENS_JS, "JSON.stringify(meta).match(/", "/)"))
    assert embedded_token.search(quoted).group(1) == SESSION_TOKEN_RE.search(quoted).group(1)


def _js_regex(program: str, opener: str, closer: str) -> str:
    """The regex source the in-page program carries between `opener` and the following `closer`."""
    start = program.index(opener) + len(opener)
    return program[start : program.index(closer, start)]
