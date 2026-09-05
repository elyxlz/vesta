import asyncio
import pathlib as pl
import sys
import time

import pytest
from vesta_browser import chromium, serve, sessions
from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes
from .hermetic import isolated_path
from .waiting import POLL_DEADLINE_SECS, POLL_INTERVAL_SECS, pid_alive, wait_for_state, wait_until_dead, with_daemon

FAKE = pl.Path(__file__).parent / "fake_camoufox"
BUDGET_SECS = 1.5


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(FAKE))
    bin_dir = isolated_path(tmp_path, monkeypatch)
    env = write_fakes(bin_dir)
    exe = tmp_path / "camoufox"
    exe.write_text("")
    env.update({"VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(exe)})
    return load_paths(env, tmp_path)


def _exec(session, code, mode=None, timeout_s=10, request_id="r1"):
    return {"version": 1, "op": "exec", "request_id": request_id, "session": session, "mode": mode, "timeout_s": timeout_s, "code": code}


async def _wait_for_file(path, timeout=POLL_DEADLINE_SECS):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(POLL_INTERVAL_SECS)
    raise AssertionError(f"{path} was never created")


def test_exec_on_a_new_session_starts_chromium_and_returns_the_full_envelope(paths):
    async def run():
        return await serve.request(paths, _exec("research", "print('hi')"))

    res = with_daemon(paths, run)
    assert res["ok"] is True and res["session"]["engine"] == "chromium" and res["session"]["state"] == "ready"
    assert res["page"]["url"] == "https://example.com/" and res["output"]["exit_code"] == 0
    assert res["artifacts"] == [] and res["warnings"] == []


def test_stealth_exec_runs_camoufox_and_pins_the_session(paths):
    async def run():
        first = await serve.request(paths, _exec("s", "print(1)", mode="stealth"))
        conflict = await serve.request(paths, _exec("s", "print(1)", mode="standard", request_id="r2"))
        inherit = await serve.request(paths, _exec("s", "print(2)", request_id="r3"))
        return first, conflict, inherit

    first, conflict, inherit = with_daemon(paths, run)
    assert first["session"]["engine"] == "camoufox" and first["output"]["stdout"] == "1\n"
    assert conflict["ok"] is False and conflict["error"]["code"] == "session_engine_conflict"
    assert inherit["session"]["engine"] == "camoufox"


def test_a_screenshot_becomes_an_artifact(paths):
    async def run():
        return await serve.request(paths, _exec("research", "SHOT"))

    res = with_daemon(paths, run)
    assert len(res["artifacts"]) == 1 and res["artifacts"][0]["mime_type"] == "image/png"
    assert res["artifacts"][0]["path"].startswith(str(paths.artifacts / "research"))


def test_failed_code_is_execution_failed_with_stderr_kept(paths):
    async def run():
        return await serve.request(paths, _exec("research", "FAIL"))

    res = with_daemon(paths, run)
    assert res["ok"] is False and res["error"]["code"] == "execution_failed" and res["error"]["phase"] == "execution"
    assert "boom" in res["output"]["stderr"] and res["session"]["state"] == "ready" and res["page"]["state"] == "ready"


def test_cdp_on_camoufox_is_a_capability_mismatch(paths):
    async def run():
        return await serve.request(paths, _exec("s", "cdp('x')", mode="stealth"))

    res = with_daemon(paths, run)
    assert res["error"]["code"] == "engine_capability_mismatch" and "camoufox" in res["error"]["message"]
    assert res["error"]["retryable"] is False and "new" in res["error"]["suggested_action"]


def test_timeout_is_clamped_and_reported(paths):
    async def run():
        clamped = await serve.request(paths, _exec("research", "print(1)", timeout_s=1))
        timed_out = await serve.request(paths, _exec("research", "SLEEP", timeout_s=5, request_id="r2"))
        return clamped, timed_out

    clamped, timed_out = with_daemon(paths, run)
    assert "timeout_clamped" in clamped["warnings"]
    assert timed_out["error"]["code"] == "timed_out" and timed_out["error"]["retryable"] is True


def test_camoufox_timeout_restarts_the_worker_on_the_next_exec(paths):
    async def run():
        first = await serve.request(paths, _exec("s", "import time; time.sleep(30)", mode="stealth", timeout_s=5))
        second = await serve.request(paths, _exec("s", "print('back')", request_id="r2"))
        return first, second

    first, second = with_daemon(paths, run)
    assert first["error"]["code"] == "timed_out" and first["session"]["state"] == "stopped"
    assert second["ok"] is True and "worker_restarted" in second["warnings"]


def test_cancel_ends_an_inflight_exec(paths):
    async def run():
        task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await wait_for_state(paths, "research", "busy")
        cancel = await serve.request(paths, {"version": 1, "op": "cancel", "request_id": "c1", "target_request_id": "r1"})
        return cancel, await task

    cancel, res = with_daemon(paths, run)
    assert cancel["ok"] is True
    assert res["error"]["code"] == "cancelled" and res["session"]["state"] == "ready"


def test_busy_session_refuses_a_second_exec(paths):
    async def run():
        task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await wait_for_state(paths, "research", "busy")
        second = await serve.request(paths, _exec("research", "print(1)", request_id="r2"))
        await serve.request(paths, {"version": 1, "op": "cancel", "request_id": "c1", "target_request_id": "r1"})
        await task
        return second

    second = with_daemon(paths, run)
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

    listing, stopped, after, stop_all, final = with_daemon(paths, run)
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

    for res in with_daemon(paths, run):
        assert res["ok"] is False and res["error"]["code"] == "invalid_request"


def test_idle_sweep_stops_a_ready_session(paths, monkeypatch):
    monkeypatch.setattr(serve, "IDLE_SWEEP_SECS", 0.2)
    monkeypatch.setattr(serve, "IDLE_STOP_SECS", 0)

    async def run():
        await serve.request(paths, _exec("research", "print(1)"))
        await wait_for_state(paths, "research", "stopped")
        return await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})

    res = with_daemon(paths, run)
    assert res["data"]["sessions"][0]["state"] == "stopped"


def test_the_idle_sweep_survives_a_failing_pass(paths, monkeypatch):
    """One raised exception must not end the loop that stops every idle browser for this daemon's life."""
    monkeypatch.setattr(serve, "IDLE_SWEEP_SECS", 0.05)
    monkeypatch.setattr(serve, "IDLE_STOP_SECS", 0)
    original = serve.stop_session
    calls = []

    async def flaky(session, *, force=False):
        calls.append(session.name)
        if len(calls) == 1:
            raise RuntimeError("sweep boom")
        return await original(session, force=force)

    monkeypatch.setattr(serve, "stop_session", flaky)

    async def run():
        await serve.request(paths, _exec("research", "print(1)"))
        await wait_for_state(paths, "research", "stopped")
        return len(calls)

    assert with_daemon(paths, run) >= 2


def test_a_total_start_failure_frees_the_session_and_kills_the_browser(paths, monkeypatch):
    """A failure the engine cannot name still has to leave no browser behind and no wedged session."""

    def _garbage(_url):
        raise ValueError("devtools answered with garbage")

    async def run():
        original = chromium._fetch_json
        monkeypatch.setattr(chromium, "_fetch_json", _garbage)
        failed = await serve.request(paths, _exec("research", "print(1)"))
        listing = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})
        pid = int((paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        dead = await wait_until_dead(pid)
        monkeypatch.setattr(chromium, "_fetch_json", original)
        recovered = await serve.request(paths, _exec("research", "print(1)", request_id="r2"))
        return failed, listing, dead, recovered

    failed, listing, dead, recovered = with_daemon(paths, run)
    assert failed["ok"] is False and failed["error"]["code"] == "engine_unavailable"
    assert listing["data"]["sessions"][0]["state"] == "stopped"
    assert dead is True
    assert recovered["ok"] is True


def test_a_stop_marks_the_session_before_it_awaits_the_engine(paths, monkeypatch):
    """An exec racing a stop must find a `stopped` session, never one the stop is still tearing down."""
    seen = {}
    original = chromium.stop

    async def _record_then_stop(runtime, session):
        seen["state"] = session.state
        seen["runtime"] = session.runtime
        await original(runtime, session)

    async def run():
        table = sessions.load_table(paths)
        session = sessions.resolve_session(table, "research", None)
        session.runtime = await chromium.start(session, paths)
        sessions.mark(session, "ready")
        monkeypatch.setattr(serve.ENGINES["chromium"], "stop", _record_then_stop)
        await serve.stop_session(session, force=True)
        return seen

    assert asyncio.run(run()) == {"state": "stopped", "runtime": None}


def test_shutdown_kills_a_session_whose_engine_stop_hangs(paths, monkeypatch):
    """The stop budget is below the SIGKILL `browser daemon stop` lands, so nothing outlives the daemon."""

    async def _hang(_runtime, _session):
        await asyncio.sleep(60)

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        session = sessions.resolve_session(state.table, "research", None)
        session.runtime = await chromium.start(session, paths)
        sessions.mark(session, "ready")
        pid = int((session.profile_dir / "fake.pid").read_text())
        monkeypatch.setattr(serve, "SHUTDOWN_BUDGET_SECS", BUDGET_SECS)
        monkeypatch.setattr(serve.ENGINES["chromium"], "stop", _hang)
        started = time.monotonic()
        await serve.shutdown(state)
        return time.monotonic() - started, await wait_until_dead(pid)

    elapsed, dead = asyncio.run(run())
    # Above the floor a budget is clamped to, so the wait really is the patched budget and not it.
    assert BUDGET_SECS <= elapsed < 5
    assert dead is True


def test_shutdown_ends_an_inflight_exec_and_kills_its_processes(paths):
    async def run():
        server = asyncio.create_task(serve.serve(paths))
        for _ in range(100):
            if paths.socket.exists():
                break
            await asyncio.sleep(0.02)
        exec_task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=30)))
        await wait_for_state(paths, "research", "busy")
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
    assert pid_alive(chromium_pid) is False
    assert pid_alive(exec_pid) is False


def test_two_concurrent_cold_execs_launch_the_browser_once(paths):
    async def run():
        first = asyncio.create_task(serve.request(paths, _exec("cold", "print(1)")))
        second = asyncio.create_task(serve.request(paths, _exec("cold", "print(1)", request_id="r2")))
        return await asyncio.gather(first, second)

    results = with_daemon(paths, run)
    oks = [r for r in results if r["ok"]]
    refused = [r for r in results if not r["ok"]]
    assert len(oks) == 1 and len(refused) == 1
    assert refused[0]["error"]["code"] == "invalid_request"
    launches = (paths.profiles / "chromium" / "cold" / "launches").read_text().splitlines()
    assert len(launches) == 1


def test_session_stop_refuses_a_busy_session_and_the_exec_still_completes(paths):
    async def run():
        exec_task = asyncio.create_task(serve.request(paths, _exec("research", "SLEEP", timeout_s=3)))
        await wait_for_state(paths, "research", "busy")
        stop = await serve.request(paths, {"version": 1, "op": "session_stop", "request_id": "s1", "session": "research"})
        chromium_pid = int((paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        alive_right_after_refusal = pid_alive(chromium_pid)
        exec_result = await exec_task
        after = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})
        return stop, alive_right_after_refusal, exec_result, after

    stop, alive_right_after_refusal, exec_result, after = with_daemon(paths, run)
    assert stop["ok"] is False and stop["error"]["code"] == "invalid_request" and "busy" in stop["error"]["message"]
    assert alive_right_after_refusal is True
    assert exec_result["error"]["code"] == "timed_out"
    assert after["data"]["sessions"][0]["state"] == "ready"


def test_stop_all_excludes_a_busy_session(paths):
    async def run():
        await serve.request(paths, _exec("a", "print(1)"))
        busy_task = asyncio.create_task(serve.request(paths, _exec("a", "SLEEP", timeout_s=3, request_id="r2")))
        await wait_for_state(paths, "a", "busy")
        await serve.request(paths, _exec("b", "print(1)", request_id="r3"))
        stop_all = await serve.request(paths, {"version": 1, "op": "stop_all", "request_id": "sa"})
        busy_result = await busy_task
        return stop_all, busy_result

    stop_all, busy_result = with_daemon(paths, run)
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

    first, second = with_daemon(paths, run)
    assert first["ok"] is False and first["error"]["code"] == "execution_failed" and "boom" in first["error"]["message"]
    assert len(first["error"]["message"].splitlines()) == 1
    assert second["ok"] is True
