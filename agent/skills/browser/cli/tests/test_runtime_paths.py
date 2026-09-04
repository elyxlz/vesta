import pathlib as pl

from vesta_browser.runtime_paths import load_paths


def test_defaults_hang_off_home_and_the_skill_dir(tmp_path):
    paths = load_paths({}, tmp_path)
    assert paths.socket == tmp_path / "agent/data/browser/browser.sock"
    assert paths.profiles == tmp_path / "agent/data/browser/profiles"
    assert paths.sessions == tmp_path / "agent/data/browser/sessions"
    assert paths.artifacts == tmp_path / "agent/data/browser/artifacts"
    assert paths.daemons_dir == tmp_path / "agent/data/daemons"
    assert paths.log == tmp_path / "agent/logs/browser.log"
    assert paths.notifications == tmp_path / "agent/notifications"
    assert paths.chromium_exe == pl.Path("/usr/bin/chromium")
    assert paths.browser_use_bin.name == "browser-use" and "engines/chromium/.venv/bin" in str(paths.browser_use_bin)
    assert paths.camoufox_python.name == "python" and "engines/camoufox/.venv/bin" in str(paths.camoufox_python)
    assert paths.worker_script.name == "worker.py" and paths.worker_script.parent.name == "camoufox"
    assert str(paths.camoufox_exe).startswith("/opt/camoufox/") and paths.camoufox_exe.name == "camoufox"


def test_env_overrides_every_binary(tmp_path):
    env = {
        "VESTA_BROWSER_CHROMIUM": "/x/chromium",
        "VESTA_BROWSER_BROWSER_USE": "/x/browser-use",
        "VESTA_BROWSER_CAMOUFOX_PYTHON": "/x/python",
        "VESTA_BROWSER_CAMOUFOX_EXE": "/x/camoufox",
    }
    paths = load_paths(env, tmp_path)
    assert (paths.chromium_exe, paths.browser_use_bin, paths.camoufox_python, paths.camoufox_exe) == (
        pl.Path("/x/chromium"),
        pl.Path("/x/browser-use"),
        pl.Path("/x/python"),
        pl.Path("/x/camoufox"),
    )
