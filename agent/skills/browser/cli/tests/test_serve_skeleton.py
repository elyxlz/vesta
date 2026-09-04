import asyncio

import pytest
from vesta_browser import serve
from vesta_browser.runtime_paths import load_paths


@pytest.fixture
def paths(tmp_path):
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


def test_engines_reports_readiness_from_binaries(paths, tmp_path):
    async def run():
        return await serve.request(paths, {"version": 1, "op": "engines", "request_id": "r1"})

    res = asyncio.run(_serve_for(paths, run()))
    routes = res["data"]["routes"]
    assert routes["standard"]["engine"] == "chromium" and routes["standard"]["protocol"] == "cdp"
    assert routes["stealth"]["engine"] == "camoufox" and routes["stealth"]["protocol"] == "playwright-firefox"
    assert routes["standard"]["ready"] is False  # /usr/bin/chromium is not on the test box's path override
    assert res["data"]["portable_helpers"][0] == "new_tab"
    assert res["data"]["profiles_shared_between_engines"] is False


def test_ping_is_false_with_no_daemon(paths):
    assert serve.ping(paths, timeout=0.2) is False
