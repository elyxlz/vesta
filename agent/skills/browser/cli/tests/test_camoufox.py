import asyncio
import dataclasses
import json
import os
import pathlib as pl
import sys

import pytest
from vesta_browser import camoufox, sessions
from vesta_browser.runtime_paths import load_paths

FAKE = pl.Path(__file__).parent / "fake_camoufox"

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
        runtime = await camoufox.start(session, paths)
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
        runtime = await camoufox.start(session, paths)
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
        runtime = await camoufox.start(session, paths)
        try:
            return await camoufox.exec_code(runtime, session, paths, "cdp('x')", timeout_s=10)
        finally:
            await camoufox.stop(runtime, session)

    outcome = asyncio.run(run())
    assert outcome.exit_code == 1 and outcome.capability_mismatch == "cdp"


def test_timeout_kills_the_worker(rig):
    paths, session = rig

    async def run():
        runtime = await camoufox.start(session, paths)
        outcome = await camoufox.exec_code(runtime, session, paths, "import time; time.sleep(30)", timeout_s=1)
        return outcome, runtime.process.returncode

    outcome, code = asyncio.run(run())
    assert outcome.timed_out is True and code is not None


def test_missing_binary_is_engine_unavailable(tmp_path):
    paths = load_paths({"VESTA_BROWSER_CAMOUFOX_EXE": str(tmp_path / "nope")}, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "s", "stealth")
    with pytest.raises(camoufox.p.BrowserError) as excinfo:
        asyncio.run(camoufox.start(session, paths))
    assert excinfo.value.err["code"] == "engine_unavailable"


def test_start_rejects_a_malformed_first_line_and_kills_the_worker(rig):
    paths, session = rig
    fake = _write_fake_worker(session.scratch_dir, "bad_json_worker.py", FAKE_WORKER_BAD_JSON)
    fake_paths = dataclasses.replace(paths, worker_script=fake)

    async def run():
        with pytest.raises(camoufox.p.BrowserError) as excinfo:
            await camoufox.start(session, fake_paths)
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
        task = asyncio.ensure_future(camoufox.start(session, fake_paths))
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
        runtime = await camoufox.start(session, fake_paths)
        await asyncio.wait_for(camoufox.stop(runtime, session), 5)
        return runtime.process.returncode

    assert asyncio.run(run()) is not None
