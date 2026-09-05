"""Headed launches: a real display and window geometry for the browser handover (Task 4)."""

import asyncio
import json
import pathlib as pl
import sys

import pytest
from vesta_browser import camoufox, chromium, sessions
from vesta_browser.runtime_paths import load_paths
from vesta_browser.runtimes import HeadedDisplay

from .fakes import write_fakes

FAKE = pl.Path(__file__).parent / "fake_camoufox"
HEADED = HeadedDisplay(":101", 1280, 800)


@pytest.fixture
def chromium_rig(tmp_path):
    env = write_fakes(tmp_path / "bin")
    paths = load_paths(env, tmp_path)
    table = sessions.load_table(paths)
    session = sessions.resolve_session(table, "research", None)
    return paths, session


@pytest.fixture
def camoufox_rig(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(FAKE))
    exe = tmp_path / "camoufox"
    exe.write_text("")
    env = {"VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(exe)}
    paths = load_paths(env, tmp_path)
    session = sessions.resolve_session(sessions.load_table(paths), "stealthy", "stealth")
    return paths, session


def test_launch_argv_headed_drops_headless_and_sets_window_geometry(chromium_rig):
    paths, session = chromium_rig
    argv = chromium.launch_argv(paths, session, headed=HEADED)
    assert "--headless=new" not in argv
    assert "--window-size=1280,800" in argv
    assert "--window-position=0,0" in argv
    assert "--remote-debugging-port=0" in argv and "--no-sandbox" in argv


def test_launch_argv_headless_is_unchanged(chromium_rig):
    paths, session = chromium_rig
    argv = chromium.launch_argv(paths, session)
    assert "--headless=new" in argv
    assert not any(a.startswith("--window-size=") for a in argv)


def test_chromium_start_headed_passes_display_to_the_browser_process(chromium_rig):
    paths, session = chromium_rig

    async def run():
        runtime = await chromium.start(session, paths, headed=HEADED)
        try:
            return json.loads((session.profile_dir / "env.json").read_text())
        finally:
            await chromium.stop(runtime, session)

    env_seen = asyncio.run(run())
    assert env_seen["DISPLAY"] == ":101"


def test_chromium_stop_removes_user_js(chromium_rig):
    paths, session = chromium_rig
    (session.profile_dir / "user.js").write_text("stale")

    async def run():
        runtime = await chromium.start(session, paths)
        await chromium.stop(runtime, session)

    asyncio.run(run())
    assert not (session.profile_dir / "user.js").exists()


def test_worker_argv_headed_adds_headed_and_window(chromium_rig):
    paths, session = chromium_rig
    argv = camoufox.worker_argv(paths, session, paths.root / "config.json", HEADED)
    assert "--headed" in argv and "--window" in argv
    assert argv[argv.index("--window") + 1] == "1280x800"


def test_worker_argv_headless_is_unchanged(chromium_rig):
    paths, session = chromium_rig
    argv = camoufox.worker_argv(paths, session, paths.root / "config.json", None)
    assert "--headed" not in argv and "--window" not in argv


def test_camoufox_start_headed_writes_user_js_fits_preset_and_launches_with_window(camoufox_rig):
    paths, session = camoufox_rig

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


def test_camoufox_headless_start_has_no_window_or_software_render_env(camoufox_rig):
    paths, session = camoufox_rig

    async def run():
        runtime = await camoufox.start(session, paths)
        try:
            return json.loads((session.profile_dir / "launch.json").read_text())
        finally:
            await camoufox.stop(runtime, session)

    launch = asyncio.run(run())
    assert "window" not in launch
    assert launch["env_DISPLAY"] == "" and launch["env_LIBGL_ALWAYS_SOFTWARE"] == ""


def test_camoufox_stop_removes_user_js(camoufox_rig):
    paths, session = camoufox_rig

    async def run():
        runtime = await camoufox.start(session, paths, headed=HEADED)
        await camoufox.stop(runtime, session)

    asyncio.run(run())
    assert not (session.profile_dir / "user.js").exists()
