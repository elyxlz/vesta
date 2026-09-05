"""Test-only PATH isolation: shields a `serve.serve()` run from whatever a real box has on PATH."""

import pathlib as pl
import sys
import tempfile

import pytest

from .fakes import write_display_fakes, write_fakes, write_gateway_fakes

FAKE_CAMOUFOX = pl.Path(__file__).parent / "fake_camoufox"


def isolated_path(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> pl.Path:
    """Shadows PATH with a tmp bin dir carrying the gateway fakes, plus the interpreter's own
    directory (the fakes need it, and uv/python must resolve for anything that spawns them), and
    nothing else: the daemon's startup `deregister-service` call can never reach a real vestad."""
    bin_dir = tmp_path / "bin"
    write_gateway_fakes(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{pl.Path(sys.executable).parent}")
    return bin_dir


def display_rig(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch, *, novnc: bool, camoufox: bool) -> tuple[dict[str, str], pl.Path]:
    """An isolated PATH holding the gateway, chromium, browser-use, and display fakes, with the X
    sockets under /tmp: returns the VESTA_BROWSER_* env for `load_paths` and that X11 dir, which
    the caller removes. `novnc` adds a noVNC tree, `camoufox` the fake stealth engine."""
    bin_dir = isolated_path(tmp_path, monkeypatch)
    env = write_fakes(bin_dir)
    # AF_UNIX addresses cap at 108 bytes and a pytest tmp_path plus the X socket name can pass it.
    x11_dir = pl.Path(tempfile.mkdtemp(dir="/tmp"))
    write_display_fakes(bin_dir, x11_dir)
    env["VESTA_BROWSER_X11_DIR"] = str(x11_dir)
    if novnc:
        novnc_dir = tmp_path / "novnc"
        (novnc_dir / "core").mkdir(parents=True)
        (novnc_dir / "core" / "rfb.js").write_text("export default class RFB {}\n")
        (novnc_dir / "vendor").mkdir()
        env["VESTA_BROWSER_NOVNC_DIR"] = str(novnc_dir)
    if camoufox:
        exe = tmp_path / "camoufox"
        exe.write_text("")
        env.update({"VESTA_BROWSER_CAMOUFOX_PYTHON": sys.executable, "VESTA_BROWSER_CAMOUFOX_EXE": str(exe)})
        monkeypatch.setenv("PYTHONPATH", str(FAKE_CAMOUFOX))
    return env, x11_dir
