import asyncio
import json
import sys

import pytest
from vesta_browser import client, procs, serve
from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths

from .fakes import write_display_fakes, write_fakes
from .hermetic import isolated_path
from .waiting import request, wait_for_socket, wait_until_all_dead, with_daemon

SLEEPER = "import time; time.sleep(60)"

BINARY_KEYS = {"VESTA_BROWSER_CHROMIUM", "VESTA_BROWSER_BROWSER_USE", "VESTA_BROWSER_CAMOUFOX_PYTHON", "VESTA_BROWSER_CAMOUFOX_EXE"}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    isolated_path(tmp_path, monkeypatch)
    return load_paths({}, tmp_path)


def test_status_answers_over_the_socket(paths):
    async def run():
        return await request(paths, p.request("status", "r1"))

    res = with_daemon(paths, run)
    assert res["ok"] is True and res["op"] == "status" and res["request_id"] == "r1"
    assert res["data"]["protocol_version"] == 1 and res["data"]["pid"] > 0


def test_unknown_version_and_op_are_invalid_requests(paths):
    async def run():
        bad_version = await request(paths, {**p.request("status", "r1"), "version": 99})
        bad_op = await request(paths, p.request("dance", "r2"))
        return bad_version, bad_op

    bad_version, bad_op = with_daemon(paths, run)
    assert bad_version["ok"] is False and bad_version["error"]["code"] == "invalid_request"
    assert bad_op["ok"] is False and bad_op["error"]["code"] == "invalid_request" and bad_op["error"]["phase"] == "validation"


def test_missing_request_id_answers_without_dropping_the_connection(paths):
    async def run():
        missing = await request(paths, {"version": p.PROTOCOL_VERSION, "op": "status"})
        follow_up = await request(paths, p.request("status", "r2"))
        return missing, follow_up

    missing, follow_up = with_daemon(paths, run)
    assert missing["ok"] is False and missing["error"]["code"] == "invalid_request"
    assert follow_up["ok"] is True and follow_up["request_id"] == "r2"


def test_socket_is_private(paths):
    async def run():
        return oct(paths.socket.stat().st_mode & 0o777)

    assert with_daemon(paths, run) == "0o600"


def _engines(paths):
    async def run():
        return await request(paths, p.request("engines", "r1"))

    return with_daemon(paths, run)


def test_engines_reports_the_route_table(paths):
    res = _engines(paths)
    routes = res["data"]["routes"]
    assert routes["standard"]["engine"] == "chromium" and routes["standard"]["protocol"] == "cdp"
    assert routes["stealth"]["engine"] == "camoufox" and routes["stealth"]["protocol"] == "playwright-firefox"
    assert res["data"]["portable_helpers"][0] == "new_tab"
    assert res["data"]["profiles_shared_between_engines"] is False


def test_engines_reports_not_ready_when_the_binaries_are_missing(tmp_path, monkeypatch):
    isolated_path(tmp_path, monkeypatch)
    missing = {key: str(tmp_path / f"missing-{key.lower()}") for key in BINARY_KEYS}
    routes = _engines(load_paths(missing, tmp_path))["data"]["routes"]
    assert routes["standard"]["ready"] is False and routes["stealth"]["ready"] is False


def test_engines_reports_ready_when_every_binary_is_present(tmp_path, monkeypatch):
    bin_dir = isolated_path(tmp_path, monkeypatch)
    write_display_fakes(bin_dir, tmp_path / "x11")
    camoufox_exe = tmp_path / "camoufox"
    camoufox_exe.touch()
    env = {**write_fakes(bin_dir), "VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(camoufox_exe)}
    assert set(env) == BINARY_KEYS
    res = _engines(load_paths(env, tmp_path))["data"]
    assert res["display"]["ready"] is True
    assert res["routes"]["standard"]["ready"] is True and res["routes"]["stealth"]["ready"] is True


def test_ping_is_false_with_no_daemon(paths):
    assert client.ping(paths, timeout=0.2) is False


def _status(paths):
    async def run():
        return await request(paths, p.request("status", "r1"))

    return with_daemon(paths, run)


def test_the_daemon_deregisters_the_browser_route_before_it_listens(tmp_path, monkeypatch):
    """A SIGKILLed daemon leaves the route behind, so every start reconciles it."""
    isolated_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_REGISTER_LOG", str(tmp_path / "register.log"))

    assert _status(load_paths({}, tmp_path))["ok"] is True
    assert (tmp_path / "register.log").read_text() == "deregister browser\n"


def test_the_daemon_starts_with_no_gateway_helpers_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    assert _status(load_paths({}, tmp_path))["ok"] is True


def test_the_daemon_ends_what_a_dead_daemon_left_running_before_it_listens(paths):
    """The ledger names a dead daemon's children and a session's record names its harness daemon;
    both are ended before the socket answers, so no display, port, or profile lock is still held."""

    async def run():
        orphan = await asyncio.create_subprocess_exec(sys.executable, "-c", SLEEPER, start_new_session=True)
        harness = await asyncio.create_subprocess_exec(sys.executable, "-c", SLEEPER, "browser_harness", start_new_session=True)
        await asyncio.to_thread(procs.record, paths.children_ledger, orphan.pid)
        record = paths.sessions / "research" / "runtime" / "bu.pid"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"pid": harness.pid}))
        server = asyncio.create_task(serve.serve(paths))
        try:
            await wait_for_socket(paths)
            dead = await wait_until_all_dead([orphan.pid, harness.pid])
            return dead, paths.children_ledger.read_text(), record.exists()
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server
            for process in (orphan, harness):
                if process.returncode is None:
                    process.kill()
                await process.wait()

    dead, ledger, record_kept = asyncio.run(run())
    assert dead is True
    assert ledger == ""
    assert record_kept is False
