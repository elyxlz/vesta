import asyncio
import json
import os
import signal
import sys

import pytest
from vesta_browser import chromium, sessions
from vesta_browser.runtime_paths import load_paths

from .fakes import write_fakes


@pytest.fixture
def rig(tmp_path):
    env = write_fakes(tmp_path / "bin")
    paths = load_paths(env, tmp_path)
    table = sessions.load_table(paths)
    session = sessions.resolve_session(table, "research", None)
    return paths, session


def _run(coro):
    return asyncio.run(coro)


def test_launch_argv_is_headless_sandboxless_and_profile_scoped(rig):
    paths, session = rig
    argv = chromium.launch_argv(paths, session)
    assert argv[0] == str(paths.chromium_exe)
    assert "--headless=new" in argv and "--no-sandbox" in argv and "--remote-debugging-port=0" in argv
    assert f"--user-data-dir={session.profile_dir}" in argv


def test_child_env_is_minimal_and_points_the_harness_at_the_session(rig, monkeypatch):
    _paths, session = rig
    monkeypatch.setenv("AGENT_TOKEN", "secret")
    monkeypatch.setenv("PYTHONPATH", "/x")
    monkeypatch.setenv("DISPLAY", ":99")
    env = chromium.child_env(session, 4321)
    assert set(env) == {
        "PATH",
        "HOME",
        "LANG",
        "TMPDIR",
        "BH_RUNTIME_DIR",
        "BH_TMP_DIR",
        "BH_HOME",
        "BU_NAME",
        "BU_CDP_URL",
        "BH_UPDATE_CHECK",
        "BH_TELEMETRY",
        "PYTHONUNBUFFERED",
    }
    assert env["BU_NAME"] == "research" and env["BU_CDP_URL"] == "http://127.0.0.1:4321"
    assert env["BH_RUNTIME_DIR"] == str(session.scratch_dir / "runtime") and env["BH_TMP_DIR"] == str(session.scratch_dir / "tmp")
    assert env["BH_UPDATE_CHECK"] == "0" and env["BH_TELEMETRY"] == "0"


def test_start_discovers_the_devtools_port_and_exec_runs_the_child(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        try:
            outcome = await chromium.exec_code(runtime, session, paths, "print('hi')", timeout_s=10)
            page = await chromium.observe(runtime)
        finally:
            await chromium.stop(runtime, session)
        return runtime, outcome, page

    runtime, outcome, page = _run(run())
    assert runtime.port > 0 and outcome.exit_code == 0 and not outcome.timed_out
    env_seen = json.loads(outcome.stdout.strip().splitlines()[-1])
    assert env_seen["BU_CDP_URL"] == f"http://127.0.0.1:{runtime.port}"
    assert page == {
        "state": "ready",
        "tab_id": "T1",
        "url": "https://example.com/",
        "title": "Example Domain",
        "observed_at": page["observed_at"],
    }
    assert runtime.process.returncode is not None


def test_timeout_kills_the_child_and_keeps_the_browser(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        try:
            outcome = await chromium.exec_code(runtime, session, paths, "SLEEP", timeout_s=1)
            alive = runtime.process.returncode is None
        finally:
            await chromium.stop(runtime, session)
        return outcome, alive

    outcome, alive = _run(run())
    assert outcome.timed_out is True and alive is True


def test_a_failing_child_reports_its_exit_code_and_stderr(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        try:
            return await chromium.exec_code(runtime, session, paths, "FAIL", timeout_s=10)
        finally:
            await chromium.stop(runtime, session)

    outcome = _run(run())
    assert outcome.exit_code == 1 and "boom" in outcome.stderr


def test_start_fails_engine_unavailable_when_the_binary_is_missing(tmp_path):
    paths = load_paths({"VESTA_BROWSER_CHROMIUM": str(tmp_path / "nope")}, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "research", None)
    with pytest.raises(chromium.p.BrowserError) as excinfo:
        _run(chromium.start(session, paths))
    assert excinfo.value.err["code"] == "engine_unavailable" and excinfo.value.err["phase"] == "launch"


def test_observe_returns_unavailable_when_a_target_entry_is_malformed(rig):
    paths, session = rig
    (session.profile_dir / "malformed-list").touch()

    async def run():
        runtime = await chromium.start(session, paths)
        try:
            return await chromium.observe(runtime)
        finally:
            await chromium.stop(runtime, session)

    assert _run(run()) == {"state": "unavailable"}


def test_start_kills_chromium_when_cancelled_before_devtools_is_ready(rig, monkeypatch):
    paths, session = rig
    monkeypatch.setattr(chromium, "CHROMIUM_READY_TIMEOUT_SECS", 60)
    (session.profile_dir / "no-port").touch()
    pid_file = session.profile_dir / "fake.pid"

    async def run():
        task = asyncio.ensure_future(chromium.start(session, paths))
        loop = asyncio.get_running_loop()
        pid_deadline = loop.time() + 5
        while True:
            if pid_file.is_file():
                break
            if loop.time() > pid_deadline:
                raise TimeoutError("fake chromium never wrote fake.pid")
            await asyncio.sleep(0.05)
        pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        death_deadline = loop.time() + 2
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            if loop.time() > death_deadline:
                return False
            await asyncio.sleep(0.05)

    assert _run(run()) is True


async def _spawn_marked(marker: str) -> asyncio.subprocess.Process:
    """A process whose argv carries `marker`, so /proc/<pid>/cmdline decides its identity."""
    return await asyncio.create_subprocess_exec(sys.executable, "-c", "import time; time.sleep(30)", marker)


def _write_harness_record(session, pid: int):
    record = session.scratch_dir / "runtime" / "bu.pid"
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({"pid": pid, "started": 1}))
    return record


def test_stop_kills_the_harness_daemon_the_record_names_and_drops_the_record(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        harness = await _spawn_marked("browser_harness.daemon")
        record = _write_harness_record(session, harness.pid)
        await chromium.stop(runtime, session)
        await asyncio.wait_for(harness.wait(), 5)
        return harness.returncode, record.exists()

    returncode, record_kept = _run(run())
    assert returncode == -signal.SIGTERM
    assert record_kept is False


def test_stop_leaves_a_recycled_pid_alone(rig):
    paths, session = rig

    async def run():
        runtime = await chromium.start(session, paths)
        stranger = await _spawn_marked("some-other-program")
        _write_harness_record(session, stranger.pid)
        await chromium.stop(runtime, session)
        survived = stranger.returncode is None and chromium._pid_alive(stranger.pid)
        stranger.terminate()
        await stranger.wait()
        return survived

    assert _run(run()) is True
