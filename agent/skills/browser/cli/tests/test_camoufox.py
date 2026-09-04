import asyncio
import json
import pathlib as pl
import sys

import pytest
from vesta_browser import camoufox, sessions
from vesta_browser.runtime_paths import load_paths

FAKE = pl.Path(__file__).parent / "fake_camoufox"


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
