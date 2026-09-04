"""Every filesystem location the daemon touches, resolved once at startup and passed down.

Tests inject binaries through the four VESTA_BROWSER_* overrides; production reads the defaults.
"""

from __future__ import annotations

import dataclasses
import pathlib as pl
import typing as tp

SKILL_DIR = pl.Path(__file__).resolve().parents[3]
ENGINES_DIR = SKILL_DIR / "engines"
CAMOUFOX_INSTALL_ROOT = pl.Path("/opt/camoufox")
# Duplicated in camoufox_install.py, which runs standalone under the system python and cannot
# import this package; test_camoufox_install.py pins the two values equal.
CAMOUFOX_RELEASE_TAG = "v150.0.2-beta.25"


@dataclasses.dataclass(frozen=True)
class Paths:
    root: pl.Path
    socket: pl.Path
    profiles: pl.Path
    sessions: pl.Path
    artifacts: pl.Path
    daemons_dir: pl.Path
    log: pl.Path
    notifications: pl.Path
    chromium_exe: pl.Path
    browser_use_bin: pl.Path
    camoufox_python: pl.Path
    camoufox_exe: pl.Path
    worker_script: pl.Path
    presets_dir: pl.Path


def _override(env: tp.Mapping[str, str], key: str, default: pl.Path) -> pl.Path:
    return pl.Path(env[key]) if key in env else default


def load_paths(env: tp.Mapping[str, str], home: pl.Path) -> Paths:
    root = home / "agent/data/browser"
    return Paths(
        root=root,
        socket=root / "browser.sock",
        profiles=root / "profiles",
        sessions=root / "sessions",
        artifacts=root / "artifacts",
        daemons_dir=home / "agent/data/daemons",
        log=home / "agent/logs/browser.log",
        notifications=home / "agent/notifications",
        chromium_exe=_override(env, "VESTA_BROWSER_CHROMIUM", pl.Path("/usr/bin/chromium")),
        browser_use_bin=_override(env, "VESTA_BROWSER_BROWSER_USE", ENGINES_DIR / "chromium/.venv/bin/browser-use"),
        camoufox_python=_override(env, "VESTA_BROWSER_CAMOUFOX_PYTHON", ENGINES_DIR / "camoufox/.venv/bin/python"),
        camoufox_exe=_override(env, "VESTA_BROWSER_CAMOUFOX_EXE", CAMOUFOX_INSTALL_ROOT / CAMOUFOX_RELEASE_TAG / "camoufox"),
        worker_script=ENGINES_DIR / "camoufox/worker.py",
        presets_dir=SKILL_DIR / "cli/src/vesta_browser/presets",
    )
