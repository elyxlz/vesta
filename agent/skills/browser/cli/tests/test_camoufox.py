import asyncio
import dataclasses
import json
import os
import pathlib as pl
import sys

import pytest
from vesta_browser import camoufox, sessions
from vesta_browser.runtime_paths import load_paths
from vesta_browser.runtimes import HeadedDisplay

FAKE = pl.Path(__file__).parent / "fake_camoufox"
HEADED = HeadedDisplay(":101", 1280, 800)

# Stand-in worker scripts, run under sys.executable (no shebang needed: worker_argv puts the
# interpreter first). Each writes its pid to <profile>/fake.pid before doing anything else, so a
# test can find it and confirm start()/stop() actually killed the process group.
FAKE_WORKER_BAD_JSON = """
import os, pathlib, sys, time
profile = sys.argv[sys.argv.index("--profile") + 1]
pathlib.Path(profile, "fake.pid").write_text(str(os.getpid()))
print("not json", flush=True)
time.sleep(30)
"""

FAKE_WORKER_SILENT = """
import os, pathlib, sys, time
profile = sys.argv[sys.argv.index("--profile") + 1]
pathlib.Path(profile, "fake.pid").write_text(str(os.getpid()))
time.sleep(30)
"""

FAKE_WORKER_COMPLAINS_AND_EXITS = """
import sys
print("camoufox-worker-stderr-marker", file=sys.stderr, flush=True)
"""

FAKE_WORKER_IGNORES_STDIN = """
import json, os, pathlib, sys, time
profile = sys.argv[sys.argv.index("--profile") + 1]
pathlib.Path(profile, "fake.pid").write_text(str(os.getpid()))
print(json.dumps({"ready": True}), flush=True)
time.sleep(30)
"""


def _write_fake_worker(scratch_dir: pl.Path, name: str, body: str) -> pl.Path:
    script = scratch_dir / name
    script.write_text(body)
    return script


async def _wait_until_dead(pid: int, deadline_s: float) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + deadline_s
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        if loop.time() > deadline:
            return False
        await asyncio.sleep(0.05)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(FAKE))
    exe = tmp_path / "camoufox"
    exe.write_text("")
    env = {"VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(exe)}
    paths = load_paths(env, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "stealthy", "stealth")
    return paths, session


def test_start_writes_the_preset_config_and_the_worker_reports_ready(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        try:
            return json.loads(runtime.config_path.read_text()), json.loads((session.profile_dir / "launch.json").read_text())
        finally:
            await camoufox.stop(runtime, session)

    config, launch = asyncio.run(run())
    assert config["showcursor"] is False and "navigator.userAgent" in config
    assert launch["user_data_dir"] == str(session.profile_dir) and launch["executable_path"] == str(paths.camoufox_exe)


def test_exec_returns_output_and_the_page(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        try:
            outcome = await camoufox.exec_code(runtime, session, paths, "new_tab('https://a'); print('ok')", timeout_s=10)
            return outcome, await camoufox.observe(runtime)
        finally:
            await camoufox.stop(runtime, session)

    outcome, page = asyncio.run(run())
    assert outcome.exit_code == 0 and outcome.stdout == "ok\n" and outcome.capability_mismatch is None
    assert page["state"] == "ready" and page["url"] == "https://a"


def test_capability_mismatch_is_surfaced(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        try:
            return await camoufox.exec_code(runtime, session, paths, "cdp('x')", timeout_s=10)
        finally:
            await camoufox.stop(runtime, session)

    outcome = asyncio.run(run())
    assert outcome.exit_code == 1 and outcome.capability_mismatch == "cdp"


def test_timeout_kills_the_worker(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        outcome = await camoufox.exec_code(runtime, session, paths, "import time; time.sleep(30)", timeout_s=1)
        return outcome, runtime.process.returncode

    outcome, code = asyncio.run(run())
    assert outcome.timed_out is True and code is not None


def test_missing_binary_is_engine_unavailable(tmp_path):
    paths = load_paths({"VESTA_BROWSER_CAMOUFOX_EXE": str(tmp_path / "nope")}, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "s", "stealth")
    with pytest.raises(camoufox.p.BrowserError) as excinfo:
        asyncio.run(camoufox.start(session, paths, headed=HEADED))
    assert excinfo.value.err["code"] == "engine_unavailable"


def test_start_rejects_a_malformed_first_line_and_kills_the_worker(rig):
    paths, session = rig
    fake = _write_fake_worker(session.scratch_dir, "bad_json_worker.py", FAKE_WORKER_BAD_JSON)
    fake_paths = dataclasses.replace(paths, worker_script=fake)

    async def run():
        with pytest.raises(camoufox.p.BrowserError) as excinfo:
            await camoufox.start(session, fake_paths, headed=HEADED)
        pid = int((session.profile_dir / "fake.pid").read_text())
        return excinfo.value, await _wait_until_dead(pid, 2)

    err, dead = asyncio.run(run())
    assert err.err["code"] == "engine_unavailable"
    assert dead is True


def test_start_kills_the_worker_when_cancelled_before_ready(rig):
    paths, session = rig
    fake = _write_fake_worker(session.scratch_dir, "silent_worker.py", FAKE_WORKER_SILENT)
    fake_paths = dataclasses.replace(paths, worker_script=fake)

    async def run():
        task = asyncio.ensure_future(camoufox.start(session, fake_paths, headed=HEADED))
        pid_file = session.profile_dir / "fake.pid"
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5
        while not pid_file.is_file():
            if loop.time() > deadline:
                raise TimeoutError("fake worker never wrote fake.pid")
            await asyncio.sleep(0.05)
        pid = int(pid_file.read_text())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return await _wait_until_dead(pid, 2)

    assert asyncio.run(run()) is True


def test_stop_kills_a_worker_that_never_answers(rig, monkeypatch):
    paths, session = rig
    monkeypatch.setattr(camoufox, "WORKER_STOP_GRACE_SECS", 0.5)
    fake = _write_fake_worker(session.scratch_dir, "stubborn_worker.py", FAKE_WORKER_IGNORES_STDIN)
    fake_paths = dataclasses.replace(paths, worker_script=fake)

    async def run():
        runtime = await camoufox.start(session, fake_paths, headed=HEADED)
        await asyncio.wait_for(camoufox.stop(runtime, session), 5)
        return runtime.process.returncode

    assert asyncio.run(run()) is not None


def test_a_failed_start_leaves_the_workers_stderr_in_the_daemon_log(rig):
    """The worker's stderr is the whole diagnosis of a browser that would not come up."""
    paths, session = rig
    fake = _write_fake_worker(session.scratch_dir, "complaining_worker.py", FAKE_WORKER_COMPLAINS_AND_EXITS)
    fake_paths = dataclasses.replace(paths, worker_script=fake)

    async def run():
        with pytest.raises(camoufox.p.BrowserError) as excinfo:
            await camoufox.start(session, fake_paths, headed=HEADED)
        return excinfo.value

    err = asyncio.run(run())
    assert err.err["code"] == "engine_unavailable"
    assert "camoufox-worker-stderr-marker" in paths.log.read_text()


def test_stop_does_not_ask_a_worker_that_has_already_exited(rig, monkeypatch):
    """A dead worker cannot answer, so the ask is skipped; only the group kill still has work to do."""
    paths, session = rig

    async def _refuse(*_args, **_kwargs):
        raise AssertionError("stop asked an exited worker")

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        await camoufox.exec_code(runtime, session, paths, "import time; time.sleep(30)", timeout_s=1)
        monkeypatch.setattr(camoufox, "_ask", _refuse)
        await asyncio.wait_for(camoufox.stop(runtime, session), 5)
        return runtime.process.returncode

    assert asyncio.run(run()) is not None


def test_worker_argv_carries_the_window_geometry_and_never_headed(rig):
    paths, session = rig
    argv = camoufox.worker_argv(paths, session, paths.root / "config.json", HEADED)
    assert "--headed" not in argv
    assert "--window" in argv
    assert argv[argv.index("--window") + 1] == "1280x800"


def test_start_writes_user_js_fits_the_preset_and_launches_onto_the_display(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        try:
            user_js = (session.profile_dir / "user.js").read_text()
            config = json.loads(runtime.config_path.read_text())
            launch = json.loads((session.profile_dir / "launch.json").read_text())
            return user_js, config, launch
        finally:
            await camoufox.stop(runtime, session)

    user_js, config, launch = asyncio.run(run())
    assert user_js == 'user_pref("gfx.webrender.software", true);\nuser_pref("gfx.x11-glx.enabled", false);\n'
    assert config["screen.width"] == 1280 and config["screen.height"] == 800
    assert launch["headless"] == "False"
    assert launch["window"] == "(1280, 800)"
    assert launch["env_DISPLAY"] == ":101"
    assert launch["env_LIBGL_ALWAYS_SOFTWARE"] == "1"


def test_stop_leaves_user_js_in_place(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        await camoufox.stop(runtime, session)

    asyncio.run(run())
    assert (session.profile_dir / "user.js").exists()
