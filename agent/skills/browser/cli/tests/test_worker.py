"""Drives the real worker script under the fake camoufox package, over its stdin/stdout protocol."""

import json
import os
import pathlib as pl
import subprocess
import sys

import pytest
from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths

FAKE = pl.Path(__file__).parent / "fake_camoufox"


@pytest.fixture
def worker(tmp_path):
    paths = load_paths({}, tmp_path)
    profile = tmp_path / "profile"
    profile.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"navigator.userAgent": "UA"}))
    proc = subprocess.Popen(
        [
            sys.executable,
            str(paths.worker_script),
            "--profile",
            str(profile),
            "--executable",
            "/opt/camoufox/x/camoufox",
            "--config",
            str(config),
            "--artifacts",
            str(artifacts),
        ],
        env={**os.environ, "PYTHONPATH": str(FAKE)},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert json.loads(proc.stdout.readline()) == {"ready": True}

    def ask(payload):
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    yield ask, profile, artifacts
    proc.kill()
    proc.wait()


def test_launch_options_are_persistent_headless_and_pinned(worker):
    _, profile, _ = worker
    launch = json.loads((profile / "launch.json").read_text())
    assert launch["persistent_context"] == "True" and launch["user_data_dir"] == str(profile)
    assert launch["executable_path"] == "/opt/camoufox/x/camoufox" and launch["headless"] == "True"
    assert launch["i_know_what_im_doing"] == "True" and "navigator.userAgent" in launch["config"]


def test_exec_captures_stdout_and_observes_the_page(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "new_tab('https://example.com'); print(page_info()['title'])"})
    assert res["exit_code"] == 0 and res["stdout"] == "Title of https://example.com\n" and res["stderr"] == ""
    assert res["page"]["url"] == "https://example.com" and res["page"]["tab_id"].startswith("tab")


def test_variables_do_not_survive_between_execs(worker):
    ask, _, _ = worker
    assert ask({"op": "exec", "code": "x = 1"})["exit_code"] == 0
    res = ask({"op": "exec", "code": "print(x)"})
    assert res["exit_code"] == 1 and "NameError" in res["stderr"]


def test_cdp_raises_a_capability_mismatch(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "cdp('Page.navigate', url='x')"})
    assert res["exit_code"] == 1 and res["capability_mismatch"] == "cdp"


def test_page_global_follows_new_tab_and_switch_tab(worker):
    ask, _, _ = worker
    code = "a = current_tab()['target_id']; new_tab('https://b'); print(page.url); switch_tab(a); print(page.url)"
    res = ask({"op": "exec", "code": code})
    assert res["stdout"] == "https://b\nabout:blank\n"


def test_screenshot_lands_in_the_artifact_dir(worker):
    ask, _, artifacts = worker
    res = ask({"op": "exec", "code": "print(capture_screenshot())"})
    printed = pl.Path(res["stdout"].strip())
    assert printed.parent == artifacts and printed.is_file()


def test_close_tab_then_observe_does_not_crash_the_worker(worker):
    ask, _, _ = worker
    ask({"op": "exec", "code": "close_tab()"})
    res = ask({"op": "observe"})
    assert res["page"] is None or "url" in res["page"]
    follow_up = ask({"op": "exec", "code": "print(1)"})
    assert follow_up["exit_code"] == 0 and follow_up["stdout"] == "1\n"


def test_fill_input_clear_first_false_types_into_the_field(worker):
    ask, _, _ = worker
    ask({"op": "exec", "code": "fill_input('#q', 'x', clear_first=False)"})
    res = ask({"op": "exec", "code": "print(context.log[-1])"})
    assert res["stdout"] == "('type_into', '#q', 'x')\n"


def test_unused_knobs_are_accepted_without_error(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "wait_for_network_idle(idle_ms=100); capture_screenshot(max_dim=800)"})
    assert res["exit_code"] == 0


def test_wait_for_element_returns_false_on_timeout_like_the_harness(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "print(wait_for_element('#never', timeout=0.1)); print(wait_for_element('#ok'))"})
    assert res["stdout"] == "False\nTrue\n"


def test_js_returns_values_and_surfaces_errors(worker):
    ask, _, _ = worker
    assert ask({"op": "exec", "code": "print(js('1 + 1'))"})["stdout"] == "2\n"
    res = ask({"op": "exec", "code": "js('throw')"})
    assert res["exit_code"] == 1 and "boom" in res["stderr"]


def test_press_key_maps_modifier_bits(worker):
    ask, _, _ = worker
    ask({"op": "exec", "code": "press_key('a', modifiers=2 | 8)"})
    res = ask({"op": "exec", "code": "print(context.log[-1])"})
    assert res["stdout"] == "('press', 'Control+Shift+a')\n"


def test_portable_helper_list_matches_the_protocol(worker):
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "print(sorted(k for k in globals() if not k.startswith('_') and k not in ('page', 'context', 'cdp')))"})
    assert json.loads(res["stdout"].replace("'", '"')) == sorted(p.PORTABLE_HELPERS)


def test_stop_ends_the_worker(worker):
    ask, _, _ = worker
    assert ask({"op": "stop"}) == {"stopped": True}


def test_a_child_writing_to_fd_1_cannot_corrupt_the_protocol_stream(worker):
    """Model code that shells out inherits fd 1; the protocol answer must still parse and carry
    nothing the child printed."""
    ask, _, _ = worker
    res = ask({"op": "exec", "code": "import os; os.system('echo stray'); print('mine')"})
    assert res["exit_code"] == 0
    assert res["stdout"] == "mine\n" and "stray" not in res["stdout"]
    assert ask({"op": "exec", "code": "print('still here')"})["stdout"] == "still here\n"
