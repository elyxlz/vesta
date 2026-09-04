import asyncio
import os
import pathlib as pl
import sys
import time

import pytest
from vesta_browser import chromium, serve
from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes

FAKE = pl.Path(__file__).parent / "fake_camoufox"
POLL_DEADLINE_SECS = 5.0
POLL_INTERVAL_SECS = 0.02


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


async def _wait_for_state(paths, name, wanted, timeout=POLL_DEADLINE_SECS):
    """Polls `sessions` until `name` reads `wanted`, instead of sleeping a fixed guess."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        listing = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "poll"})
        states = {s["name"]: s["state"] for s in listing["data"]["sessions"]}
        if name in states and states[name] == wanted:
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"session {name!r} never reached state {wanted!r}")


async def _wait_for_file(path, timeout=POLL_DEADLINE_SECS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"{path} was never created")


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


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
        await _wait_for_state(paths, "research", "busy")
        cancel = await serve.request(paths, {"version": 1, "op": "cancel", "request_id": "c1", "target_request_id": "r1"})
        return cancel, await task

    cancel, res = _with_daemon(paths, run)
    assert cancel["ok"] is True
    assert res["error"]["code"] == "cancelled" and res["session"]["state"] == "ready"


def test_busy_session_refuses_a_second_exec(paths):
    async def run():
        task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await _wait_for_state(paths, "research", "busy")
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


def test_shutdown_ends_an_inflight_exec_and_kills_its_processes(paths):
    async def run():
        server = asyncio.create_task(serve.serve(paths))
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        exec_task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await _wait_for_state(paths, "research", "busy")
        exec_pid_file = paths.sessions / "research" / "tmp" / "exec.pid"
        await _wait_for_file(exec_pid_file)
        chromium_pid = int((paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        exec_pid = int(exec_pid_file.read_text())
        server.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(server, timeout=5)
        exec_result = await exec_task
        return chromium_pid, exec_pid, exec_result

    chromium_pid, exec_pid, exec_result = asyncio.run(run())
    assert exec_result["error"]["code"] == "cancelled"
    assert _pid_alive(chromium_pid) is False
    assert _pid_alive(exec_pid) is False


def test_two_concurrent_cold_execs_launch_the_browser_once(paths):
    async def run():
        first = asyncio.create_task(serve.request(paths, _exec("cold", "print(1)")))
        second = asyncio.create_task(serve.request(paths, _exec("cold", "print(1)", request_id="r2")))
        return await asyncio.gather(first, second)

    results = _with_daemon(paths, run)
    oks = [r for r in results if r["ok"]]
    refused = [r for r in results if not r["ok"]]
    assert len(oks) == 1 and len(refused) == 1
    assert refused[0]["error"]["code"] == "invalid_request"
    launches = (paths.profiles / "chromium" / "cold" / "launches").read_text().splitlines()
    assert len(launches) == 1


def test_session_stop_refuses_a_busy_session_and_the_exec_still_completes(paths):
    async def run():
        exec_task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=3)))
        await _wait_for_state(paths, "research", "busy")
        stop = await serve.request(paths, {"version": 1, "op": "session_stop", "request_id": "s1", "session": "research"})
        chromium_pid = int((paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        alive_right_after_refusal = _pid_alive(chromium_pid)
        exec_result = await exec_task
        after = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})
        return stop, alive_right_after_refusal, exec_result, after

    stop, alive_right_after_refusal, exec_result, after = _with_daemon(paths, run)
    assert stop["ok"] is False and stop["error"]["code"] == "invalid_request" and "busy" in stop["error"]["message"]
    assert alive_right_after_refusal is True
    assert exec_result["error"]["code"] == "timed_out"
    assert after["data"]["sessions"][0]["state"] == "ready"


def test_stop_all_excludes_a_busy_session(paths):
    async def run():
        await serve.request(paths, _exec("a", "print(1)"))
        busy_task = asyncio.create_task(serve.request(paths, _exec("a", "SLEEP", timeout_s=3, request_id="r2")))
        await _wait_for_state(paths, "a", "busy")
        await serve.request(paths, _exec("b", "print(1)", request_id="r3"))
        stop_all = await serve.request(paths, {"version": 1, "op": "stop_all", "request_id": "sa"})
        busy_result = await busy_task
        return stop_all, busy_result

    stop_all, busy_result = _with_daemon(paths, run)
    assert stop_all["data"]["stopped"] == ["b"]
    assert busy_result["error"]["code"] == "timed_out"


def test_an_engine_exception_answers_execution_failed_and_the_session_recovers(paths, monkeypatch):
    async def _raise_boom(_runtime, _session, _paths, _code, _timeout_s):
        raise RuntimeError("boom")

    async def run():
        original = chromium.exec_code
        monkeypatch.setattr(chromium, "exec_code", _raise_boom)
        first = await serve.request(paths, _exec("research", "print(1)"))
        monkeypatch.setattr(chromium, "exec_code", original)
        second = await serve.request(paths, _exec("research", "print(1)", request_id="r2"))
        return first, second

    first, second = _with_daemon(paths, run)
    assert first["ok"] is False and first["error"]["code"] == "execution_failed" and "boom" in first["error"]["message"]
    assert len(first["error"]["message"].splitlines()) == 1
    assert second["ok"] is True
