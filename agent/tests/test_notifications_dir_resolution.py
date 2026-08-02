"""Skill watchers must resolve the notifications directory the way the engine does.

The engine reads `VestaConfig.notifications_dir`, which is `agent_dir / "notifications"`, and
`agent_dir` follows `$AGENT_DIR` when that is set. A watcher that writes somewhere else still
writes successfully, so the mismatch never raises: notifications are simply never delivered and
nothing complains. These tests execute each watcher's resolver in both environments and guard
against the old home-relative constant coming back anywhere under `agent/skills`.
"""

import ast
import os
import pathlib as pl
import re
import typing as tp

import pytest

import core.config as cfg

SKILLS_DIR = pl.Path(__file__).resolve().parents[1] / "skills"
WATCHERS = [
    SKILLS_DIR / "enable-banking/cli/src/finance_cli/transaction_watcher.py",
    SKILLS_DIR / "spotify/cli/src/spotify_cli/organize.py",
]
HOME_RELATIVE = re.compile(r"""Path\.home\(\)\s*/\s*["']notifications["']""")


def _load_resolver(path: pl.Path) -> tp.Callable[[], pl.Path]:
    """Execute just the module's `_notifications_dir` definition.

    Each watcher lives in its own uv project with its own third-party dependencies, which the engine
    venv does not install, so the module as a whole is not importable here. The resolver itself only
    needs `os` and `Path`, so compiling that one definition runs the shipped source verbatim.
    """
    defs = [node for node in ast.parse(path.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == "_notifications_dir"]
    assert len(defs) == 1, f"{path} should define exactly one _notifications_dir"
    namespace: dict[str, tp.Any] = {"os": os, "Path": pl.Path}
    exec(compile(ast.Module(body=list(defs), type_ignores=[]), str(path), "exec"), namespace)
    return tp.cast(tp.Callable[[], pl.Path], namespace["_notifications_dir"])


def _watcher_id(path: pl.Path) -> str:
    return path.stem


@pytest.mark.parametrize("path", WATCHERS, ids=_watcher_id)
def test_watcher_defaults_under_the_agent_dir(path: pl.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_DIR", raising=False)
    assert _load_resolver(path)() == pl.Path.home() / "agent" / "notifications"


@pytest.mark.parametrize("path", WATCHERS, ids=_watcher_id)
def test_watcher_follows_agent_dir_env(path: pl.Path, monkeypatch: pytest.MonkeyPatch, tmp_path: pl.Path) -> None:
    # tmp_path keeps this off any real notifications directory: nothing here writes a file.
    monkeypatch.setenv("AGENT_DIR", str(tmp_path))
    resolved = _load_resolver(path)()
    assert resolved == tmp_path.resolve() / "notifications"
    assert resolved == cfg.VestaConfig().notifications_dir


def test_no_skill_writes_to_the_home_notifications_dir() -> None:
    offenders = sorted(str(p.relative_to(SKILLS_DIR)) for p in SKILLS_DIR.rglob("*.py") if HOME_RELATIVE.search(p.read_text(errors="replace")))
    assert offenders == []
