import asyncio
import json
import pathlib as pl
import shutil
import sys
import tempfile
import time

import pytest
from vesta_browser import chromium, display, serve, sessions
from vesta_browser import protocol as p
from vesta_browser.runtime_paths import load_paths
from vesta_browser.runtimes import HeadedDisplay

from .fakes import write_display_fakes, write_fakes
from .hermetic import isolated_path
from .waiting import (
    POLL_DEADLINE_SECS,
    POLL_INTERVAL_SECS,
    pid_alive,
    wait_for_state,
    wait_until_all_dead,
    wait_until_dead,
    with_daemon,
)

FAKE = pl.Path(__file__).parent / "fake_camoufox"
BUDGET_SECS = 1.5
HEADED = HeadedDisplay(":101", 1280, 800)


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(FAKE))
    bin_dir = isolated_path(tmp_path, monkeypatch)
    env = write_fakes(bin_dir)
    # AF_UNIX addresses cap at 108 bytes and a pytest tmp_path plus the X socket name can pass it.
    x11_dir = pl.Path(tempfile.mkdtemp(dir="/tmp"))
    write_display_fakes(bin_dir, x11_dir)
    exe = tmp_path / "camoufox"
    exe.write_text("")
    env.update(
        {
            "VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable,
            "VESTA_BROWSER_CAMOUFOX_EXE": str(exe),
            "VESTA_BROWSER_X11_DIR": str(x11_dir),
        }
    )
    yield load_paths(env, tmp_path)
    shutil.rmtree(x11_dir, ignore_errors=True)


def _exec(session, code, mode=None, timeout_s=10, request_id="r1"):
    return {"version": 1, "op": "exec", "request_id": request_id, "session": session, "mode": mode, "timeout_s": timeout_s, "code": code}


def _display_pids(paths):
    record = paths.x11_socket_dir / "pids"
    return [int(line) for line in record.read_text().split()] if record.exists() else []


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


def test_exec_claims_a_display_and_the_browser_launches_on_it(paths):
    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        result = await serve.op_exec(state, "r1", _exec("research", "print(1)"))
        session = state.table.sessions["research"]
        env = json.loads((paths.profiles / "chromium" / "research" / "env.json").read_text())
        return result, session.display.display, env["DISPLAY"], _display_pids(paths)

    result, display_name, chromium_display, pids = asyncio.run(run())
    assert result["ok"] is True
    assert chromium_display == display_name
    assert len(pids) == 2 and all(pid_alive(pid) for pid in pids)


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


def test_two_concurrent_cold_execs_claim_one_display_each(paths):
    """Two sessions starting together share the socket dir; neither may read the other's Xvfb as its own."""

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        await asyncio.gather(serve.op_exec(state, "r1", _exec("one", "print(1)")), serve.op_exec(state, "r2", _exec("two", "print(2)")))
        first = state.table.sessions["one"].display
        second = state.table.sessions["two"].display
        alive = [pid_alive(first.xvfb.pid), pid_alive(second.xvfb.pid)]
        await serve.op_session_stop(state, "s1", {"session": "one"})
        number = display.display_number(second.display)
        survived = (paths.x11_socket_dir / f"X{number}").exists() and display.own_display_serving(paths, number)
        await serve.op_session_stop(state, "s2", {"session": "two"})
        return first.display, second.display, alive, survived

    first, second, alive, survived = asyncio.run(run())
    assert first != second
    assert alive == [True, True]
    assert survived is True


def test_a_display_the_daemon_cannot_bring_up_is_engine_unavailable(paths, tmp_path):
    """A missing display binary is the engine's own launch failure, with the pointer that names the fix."""

    (tmp_path / "bin" / "Xvfb").unlink()

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        result = await serve.handle_request(state, _exec("research", "print(1)"))
        session = state.table.sessions["research"]
        return result, session.state, session.display, _display_pids(paths)

    result, session_state, session_display, pids = asyncio.run(run())
    assert result["ok"] is False and result["error"]["code"] == "engine_unavailable"
    assert result["error"]["phase"] == "launch" and result["error"]["retryable"] is True
    assert "Xvfb" in result["error"]["message"]
    assert session_state == "stopped" and session_display is None and pids == []


def test_session_stop_ends_the_display_too(paths):
    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        await serve.op_exec(state, "r1", _exec("research", "print(1)"))
        session = state.table.sessions["research"]
        pids = [session.display.xvfb.pid, session.display.openbox.pid]
        await serve.op_session_stop(state, "s1", {"session": "research"})
        dead = await wait_until_all_dead(pids)
        return dead, session.display

    dead, display_after = asyncio.run(run())
    assert dead is True
    assert display_after is None


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
        pids = _display_pids(paths)
        await wait_for_state(paths, "research", "stopped")
        dead = await wait_until_all_dead(pids)
        listing = await serve.request(paths, {"version": 1, "op": "sessions", "request_id": "l"})
        return listing, dead

    res, dead = with_daemon(paths, run)
    assert res["data"]["sessions"][0]["state"] == "stopped"
    assert dead is True


def test_the_idle_sweep_survives_a_failing_pass(paths, monkeypatch):
    """One raised exception must not end the loop that stops every idle browser for this daemon's life."""
    monkeypatch.setattr(serve, "IDLE_SWEEP_SECS", 0.05)
    monkeypatch.setattr(serve, "IDLE_STOP_SECS", 0)
    original = serve.stop_session
    calls = []

    async def flaky(paths, session, *, force=False):
        calls.append(session.name)
        if len(calls) == 1:
            raise RuntimeError("sweep boom")
        return await original(paths, session, force=force)

    monkeypatch.setattr(serve, "stop_session", flaky)

    async def run():
        await serve.request(paths, _exec("research", "print(1)"))
        await wait_for_state(paths, "research", "stopped")
        return len(calls)

    assert with_daemon(paths, run) >= 2


def test_a_total_start_failure_frees_the_session_and_kills_the_browser(paths, monkeypatch):
    """A failure the engine cannot name still has to leave no browser, no display, and no wedged session."""

    def _garbage(_url):
        raise ValueError("devtools answered with garbage")

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        original = chromium._fetch_json
        monkeypatch.setattr(chromium, "_fetch_json", _garbage)
        failed = await serve.handle_request(state, _exec("research", "print(1)"))
        session = state.table.sessions["research"]
        state_after_failure = session.state
        display_after_failure = session.display
        pid = int((paths.profiles / "chromium" / "research" / "fake.pid").read_text())
        dead = await wait_until_dead(pid)
        display_dead = await wait_until_all_dead(_display_pids(paths))
        monkeypatch.setattr(chromium, "_fetch_json", original)
        recovered = await serve.handle_request(state, _exec("research", "print(1)", request_id="r2"))
        return failed, state_after_failure, display_after_failure, dead, display_dead, recovered

    failed, state_after, display_after, dead, display_dead, recovered = asyncio.run(run())
    assert failed["ok"] is False and failed["error"]["code"] == "engine_unavailable"
    assert state_after == "stopped"
    assert display_after is None
    assert dead is True
    assert display_dead is True
    assert recovered["ok"] is True


def test_cancelling_an_exec_while_the_engine_is_starting_frees_the_display(paths, monkeypatch):
    """A cancellation mid `ensure_running` must not leak the Xvfb and openbox it just claimed."""
    hang_started = asyncio.Event()

    async def _hang(*_args, **_kwargs):
        hang_started.set()
        await asyncio.sleep(3600)

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        monkeypatch.setattr(serve.ENGINES["chromium"], "start", _hang)
        task = asyncio.ensure_future(serve.op_exec(state, "r1", _exec("research", "print(1)")))
        await asyncio.wait_for(hang_started.wait(), 5)
        session = state.table.sessions["research"]
        display_pids = [session.display.xvfb.pid, session.display.openbox.pid]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        dead = await wait_until_all_dead(display_pids)
        return dead, session.state, session.display

    dead, state_after, display_after = asyncio.run(run())
    assert dead is True
    assert state_after == "stopped"
    assert display_after is None


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
        session.runtime = await chromium.start(session, paths, headed=HEADED)
        sessions.mark(session, "ready")
        monkeypatch.setattr(serve.ENGINES["chromium"], "stop", _record_then_stop)
        await serve.stop_session(paths, session, force=True)
        return seen

    assert asyncio.run(run()) == {"state": "stopped", "runtime": None}


def test_shutdown_kills_a_session_whose_engine_stop_hangs(paths, monkeypatch):
    """The stop budget is below the SIGKILL `browser daemon stop` lands, so nothing outlives the daemon."""

    async def _hang(_runtime, _session):
        await asyncio.sleep(60)

    async def run():
        state = serve.State(paths=paths, table=sessions.load_table(paths))
        session = sessions.resolve_session(state.table, "research", None)
        session.display = await display.start_session_display(paths)
        headed = HeadedDisplay(session.display.display, display.SCREEN_W, display.SCREEN_H)
        session.runtime = await chromium.start(session, paths, headed=headed)
        sessions.mark(session, "ready")
        pid = int((session.profile_dir / "fake.pid").read_text())
        display_pids = [session.display.xvfb.pid, session.display.openbox.pid]
        monkeypatch.setattr(serve, "SHUTDOWN_BUDGET_SECS", BUDGET_SECS)
        monkeypatch.setattr(serve.ENGINES["chromium"], "stop", _hang)
        started = time.monotonic()
        await serve.shutdown(state)
        elapsed = time.monotonic() - started
        return elapsed, await wait_until_dead(pid), await wait_until_all_dead(display_pids)

    elapsed, dead, display_dead = asyncio.run(run())
    # Above the floor a budget is clamped to, so the wait really is the patched budget and not it.
    assert BUDGET_SECS <= elapsed < 5
    assert dead is True
    assert display_dead is True


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
