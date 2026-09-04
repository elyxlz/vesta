import asyncio
import pathlib as pl
import sys

import pytest
from vesta_browser import protocol as p
from vesta_browser import serve
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes

FAKE = pl.Path(__file__).parent / "fake_camoufox"


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(FAKE))
    env = write_fakes(tmp_path / "bin")
    exe = tmp_path / "camoufox"
    exe.write_text("")
    env.update({"VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(exe)})
    return load_paths(env, tmp_path)


def _exec(session, code, mode=None, timeout_s=10, request_id="r1"):
    return {"version": 1, "op": "exec", "request_id": request_id, "session": session, "mode": mode, "timeout_s": timeout_s, "code": code}


def _with_daemon(paths, coro_fn):
    async def run():
        server = asyncio.create_task(serve.serve(paths))
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        try:
            return await coro_fn()
        finally:
            server.cancel()
            with pytest.raises(asyncio.CancelledError):
                await server

    return asyncio.run(run())


def test_exec_on_a_new_session_starts_chromium_and_returns_the_full_envelope(paths):
    async def run():
        return await serve.request(paths, _exec("research", "print('hi')"))

    res = _with_daemon(paths, run)
    assert res["ok"] is True and res["session"]["engine"] == "chromium" and res["session"]["state"] == "ready"
    assert res["page"]["url"] == "https://example.com/" and res["output"]["exit_code"] == 0
    assert res["artifacts"] == [] and res["warnings"] == []


def test_stealth_exec_runs_camoufox_and_pins_the_session(paths):
    async def run():
        first = await serve.request(paths, _exec("s", "print(1)", mode="stealth"))
        conflict = await serve.request(paths, _exec("s", "print(1)", mode="standard", request_id="r2"))
        inherit = await serve.request(paths, _exec("s", "print(2)", request_id="r3"))
        return first, conflict, inherit

    first, conflict, inherit = _with_daemon(paths, run)
    assert first["session"]["engine"] == "camoufox" and first["output"]["stdout"] == "1\n"
    assert conflict["ok"] is False and conflict["error"]["code"] == "session_engine_conflict"
    assert inherit["session"]["engine"] == "camoufox"


def test_a_screenshot_becomes_an_artifact(paths):
    async def run():
        return await serve.request(paths, _exec("research", "SHOT"))

    res = _with_daemon(paths, run)
    assert len(res["artifacts"]) == 1 and res["artifacts"][0]["mime_type"] == "image/png"
    assert res["artifacts"][0]["path"].startswith(str(paths.artifacts / "research"))


def test_failed_code_is_execution_failed_with_stderr_kept(paths):
    async def run():
        return await serve.request(paths, _exec("research", "FAIL"))

    res = _with_daemon(paths, run)
    assert res["ok"] is False and res["error"]["code"] == "execution_failed" and res["error"]["phase"] == "execution"
    assert "boom" in res["output"]["stderr"] and res["session"]["state"] == "ready" and res["page"]["state"] == "ready"


def test_cdp_on_camoufox_is_a_capability_mismatch(paths):
    async def run():
        return await serve.request(paths, _exec("s", "cdp('x')", mode="stealth"))

    res = _with_daemon(paths, run)
    assert res["error"]["code"] == "engine_capability_mismatch" and "camoufox" in res["error"]["message"]
    assert res["error"]["retryable"] is False and "new" in res["error"]["suggested_action"]


def test_timeout_is_clamped_and_reported(paths):
    async def run():
        clamped = await serve.request(paths, _exec("research", "print(1)", timeout_s=1))
        timed_out = await serve.request(paths, _exec("research", "SLEEP", timeout_s=5, request_id="r2"))
        return clamped, timed_out

    clamped, timed_out = _with_daemon(paths, run)
    assert "timeout_clamped" in clamped["warnings"]
    assert timed_out["error"]["code"] == "timed_out" and timed_out["error"]["retryable"] is True


def test_camoufox_timeout_restarts_the_worker_on_the_next_exec(paths):
    async def run():
        first = await serve.request(paths, _exec("s", "import time; time.sleep(30)", mode="stealth", timeout_s=5))
        second = await serve.request(paths, _exec("s", "print('back')", request_id="r2"))
        return first, second

    first, second = _with_daemon(paths, run)
    assert first["error"]["code"] == "timed_out" and first["session"]["state"] == "stopped"
    assert second["ok"] is True and "worker_restarted" in second["warnings"]


def test_cancel_ends_an_inflight_exec(paths):
    async def run():
        task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await asyncio.sleep(1.5)
        cancel = await serve.request(paths, {"version": 1, "op": "cancel", "request_id": "c1", "target_request_id": "r1"})
        return cancel, await task

    cancel, res = _with_daemon(paths, run)
    assert cancel["ok"] is True
    assert res["error"]["code"] == "cancelled" and res["session"]["state"] == "ready"


def test_busy_session_refuses_a_second_exec(paths):
    async def run():
        task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await asyncio.sleep(1.5)
        second = await serve.request(paths, _exec("research", "print(1)", request_id="r2"))
        await serve.request(paths, {"version": 1, "op": "cancel", "request_id": "c1", "target_request_id": "r1"})
        await task
        return second

    second = _with_daemon(paths, run)
    assert second["error"]["code"] == "invalid_request" and "busy" in second["error"]["message"]


def test_sessions_and_session_stop_and_stop_all(paths):
    async def run():
        await serve.request(paths, _exec("a", "print(1)"))
        await serve.request(paths, _exec("b", "print(1)", mode="stealth", request_id="r2"))
        listing = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})
        stopped = await serve.request(paths, {"version": 1, "op": "session_stop", "request_id": "s", "session": "a"})
        after = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l2"})
        stop_all = await serve.request(paths, {"version": 1, "op": "stop_all", "request_id": "sa"})
        final = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l3"})
        return listing, stopped, after, stop_all, final

    listing, stopped, after, stop_all, final = _with_daemon(paths, run)
    engines_and_states = {s["name"]: (s["engine"], s["state"]) for s in listing["data"]["sessions"]}
    assert engines_and_states == {"a": ("chromium", "ready"), "b": ("camoufox", "ready")}
    assert stopped["ok"] is True
    assert {s["name"]: s["state"] for s in after["data"]["sessions"]} == {"a": "stopped", "b": "ready"}
    assert stop_all["data"]["stopped"] == ["b"]
    assert all(s["state"] == "stopped" for s in final["data"]["sessions"])


def test_bad_exec_requests_are_invalid(paths):
    async def run():
        empty = await serve.request(paths, _exec("research", ""))
        huge = await serve.request(paths, _exec("research", "x" * (p.CODE_MAX_BYTES + 1), request_id="r2"))
        mode = await serve.request(paths, _exec("research", "print(1)", mode="ninja", request_id="r3"))
        return empty, huge, mode

    for res in _with_daemon(paths, run):
        assert res["ok"] is False and res["error"]["code"] == "invalid_request"


def test_idle_sweep_stops_a_ready_session(paths, monkeypatch):
    monkeypatch.setattr(serve, "IDLE_SWEEP_SECS", 0.2)
    monkeypatch.setattr(serve, "IDLE_STOP_SECS", 0)

    async def run():
        await serve.request(paths, _exec("research", "print(1)"))
        await asyncio.sleep(1.0)
        return await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})

    res = _with_daemon(paths, run)
    assert res["data"]["sessions"][0]["state"] == "stopped"
