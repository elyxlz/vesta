"""Test-only PATH isolation: shields a `serve.serve()` run from whatever a real box has on PATH."""

import pathlib as pl
import sys

import pytest

from .fakes import write_gateway_fakes


def isolated_path(tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> pl.Path:
    """Shadows PATH with a tmp bin dir carrying the gateway fakes, plus the interpreter's own
    directory (the fakes need it, and uv/python must resolve for anything that spawns them), and
    nothing else: the daemon's startup `deregister-service` call can never reach a real vestad."""
    bin_dir = tmp_path / "bin"
    write_gateway_fakes(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}:{pl.Path(sys.executable).parent}")
    return bin_dir
