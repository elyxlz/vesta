import asyncio
import sys

import pytest
from vesta_browser import serve
from vesta_browser.runtime_paths import load_paths

from .fakes import write_display_fakes, write_fakes
from .hermetic import isolated_path

BINARY_KEYS = {"VESTA_BROWSER_CHROMIUM", "VESTA_BROWSER_BROWSER_USE", "VESTA_BROWSER_CAMOUFOX_PYTHON", "VESTA_BROWSER_CAMOUFOX_EXE"}


@pytest.fixture
def paths(tmp_path, monkeypatch):
    isolated_path(tmp_path, monkeypatch)
    return load_paths({}, tmp_path)


async def _serve_for(paths, coro):
    server_task = asyncio.create_task(serve.serve(paths))
    try:
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        return await coro
    finally:
        server_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server_task


def test_status_answers_over_the_socket(paths):
    async def run():
        return await serve.request(paths, {"version": 1, "op": "status", "request_id": "r1"})

    res = asyncio.run(_serve_for(paths, run()))
    assert res["ok"] is True and res["op"] == "status" and res["request_id"] == "r1"
    assert res["data"]["protocol_version"] == 1 and res["data"]["pid"] > 0


def test_unknown_version_and_op_are_invalid_requests(paths):
    async def run():
        bad_version = await serve.request(paths, {"version": 99, "op": "status", "request_id": "r1"})
        bad_op = await serve.request(paths, {"version": 1, "op": "dance", "request_id": "r2"})
        return bad_version, bad_op

    bad_version, bad_op = asyncio.run(_serve_for(paths, run()))
    assert bad_version["ok"] is False and bad_version["error"]["code"] == "invalid_request"
    assert bad_op["ok"] is False and bad_op["error"]["code"] == "invalid_request" and bad_op["error"]["phase"] == "validation"


def test_missing_request_id_answers_without_dropping_the_connection(paths):
    async def run():
        missing = await serve.request(paths, {"version": 1, "op": "status"})
        follow_up = await serve.request(paths, {"version": 1, "op": "status", "request_id": "r2"})
        return missing, follow_up

    missing, follow_up = asyncio.run(_serve_for(paths, run()))
    assert missing["ok"] is False and missing["error"]["code"] == "invalid_request"
    assert follow_up["ok"] is True and follow_up["request_id"] == "r2"


def test_socket_is_private(paths):
    async def run():
        return oct(paths.socket.stat().st_mode & 0o777)

    assert asyncio.run(_serve_for(paths, run())) == "0o600"


def _engines(paths):
    async def run():
        return await serve.request(paths, {"version": 1, "op": "engines", "request_id": "r1"})

    return asyncio.run(_serve_for(paths, run()))


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
    assert serve.ping(paths, timeout=0.2) is False


def _status(paths):
    async def run():
        return await serve.request(paths, {"version": 1, "op": "status", "request_id": "r1"})

    return asyncio.run(_serve_for(paths, run()))


def test_the_daemon_deregisters_the_browser_route_before_it_listens(tmp_path, monkeypatch):
    """A SIGKILLed daemon leaves the route behind, so every start reconciles it."""
    isolated_path(tmp_path, monkeypatch)
    monkeypatch.setenv("FAKE_REGISTER_LOG", str(tmp_path / "register.log"))

    assert _status(load_paths({}, tmp_path))["ok"] is True
    assert (tmp_path / "register.log").read_text() == "deregister browser\n"


def test_the_daemon_starts_with_no_gateway_helpers_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))

    assert _status(load_paths({}, tmp_path))["ok"] is True
