"""Exercises the REAL dashboard build gate (agent/skills/dashboard/scripts/build.sh) against
fake `npm` and `npx` commands: dependencies are reinstalled only when the lockfile outdates the
installed tree, and dist/ is rebuilt only when a build input outdates it."""

import os
import pathlib as pl
import shutil
import subprocess

import pytest

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "agent/skills/dashboard/scripts/build.sh"

# Fixed, explicit mtimes so the gate decision never rides on wall-clock ordering: every input
# pinned OLD, both artifacts NEWER, and a single bumped path.
OLD_INPUT_MTIME = 1_600_000_000
ARTIFACT_MTIME = 1_700_000_000
BUMPED_MTIME = ARTIFACT_MTIME + 100

FAKE_TOOL = """#!/bin/sh
echo "$(basename "$0") $*" >> "$TOOL_LOG"
exit "${TOOL_EXIT:-0}"
"""

INPUTS = ("src/App.tsx", "index.html", "vite.config.ts", "package-lock.json", "tsconfig.json", "tsconfig.app.json")
ARTIFACTS = ("node_modules/.package-lock.json", "dist/index.html")
# shadcn's registry config sits beside the inputs and never reaches the bundle.
UNRELATED = "components.json"


def _fake_skill(tmp_path) -> pl.Path:
    """A byte copy of the real script beside a minimal fake app/ tree, every input pinned old and
    both artifacts newer, so the repo's own app stays untouched."""
    skill = tmp_path / "skill"
    app = skill / "app"
    (skill / "scripts").mkdir(parents=True)
    script = skill / "scripts/build.sh"
    script.write_text(BUILD_SCRIPT.read_text())
    script.chmod(0o755)
    for name in (*INPUTS, *ARTIFACTS, UNRELATED):
        (app / name).parent.mkdir(parents=True, exist_ok=True)
        (app / name).write_text("")
    for path in (app, *app.rglob("*")):
        os.utime(path, (OLD_INPUT_MTIME, OLD_INPUT_MTIME))
    for name in ARTIFACTS:
        os.utime(app / name, (ARTIFACT_MTIME, ARTIFACT_MTIME))
    return skill


def _run(tmp_path, skill, tool_exit="0") -> tuple[subprocess.CompletedProcess[str], list[str]]:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(exist_ok=True)
    for tool in ("npm", "npx"):
        (fakebin / tool).write_text(FAKE_TOOL)
        (fakebin / tool).chmod(0o755)
    log = tmp_path / "tools.log"
    env = os.environ | {"PATH": f"{fakebin}:{os.environ['PATH']}", "TOOL_LOG": str(log), "TOOL_EXIT": tool_exit}
    result = subprocess.run([str(skill / "scripts/build.sh")], env=env, capture_output=True, text=True, cwd=tmp_path, check=False)
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


@pytest.mark.parametrize(
    "bumped, expected_calls",
    [
        pytest.param(UNRELATED, [], id="current-artifacts-run-nothing"),
        pytest.param("package-lock.json", ["npm install", "npx vite build"], id="newer-lockfile-reinstalls-then-rebuilds"),
        pytest.param("src/App.tsx", ["npx vite build"], id="newer-source-rebuilds"),
        pytest.param("src", ["npx vite build"], id="removed-source-leaves-a-newer-directory-and-rebuilds"),
        pytest.param("index.html", ["npx vite build"], id="newer-entry-page-rebuilds"),
        pytest.param("tsconfig.app.json", ["npx vite build"], id="newer-tsconfig-rebuilds"),
    ],
)
def test_each_step_runs_only_when_an_input_outdates_its_artifact(tmp_path, bumped, expected_calls):
    skill = _fake_skill(tmp_path)
    os.utime(skill / "app" / bumped, (BUMPED_MTIME, BUMPED_MTIME))
    result, calls = _run(tmp_path, skill)
    assert result.returncode == 0, result.stderr
    assert calls == expected_calls


@pytest.mark.parametrize(
    "removed, expected_calls",
    [
        pytest.param("node_modules", ["npm install"], id="missing-node-modules-installs"),
        pytest.param("dist", ["npx vite build"], id="missing-dist-builds"),
    ],
)
def test_a_missing_artifact_is_made(tmp_path, removed, expected_calls):
    skill = _fake_skill(tmp_path)
    shutil.rmtree(skill / "app" / removed)
    result, calls = _run(tmp_path, skill)
    assert result.returncode == 0, result.stderr
    assert calls == expected_calls


def test_a_failed_install_stops_before_the_build(tmp_path):
    skill = _fake_skill(tmp_path)
    os.utime(skill / "app/package-lock.json", (BUMPED_MTIME, BUMPED_MTIME))
    result, calls = _run(tmp_path, skill, tool_exit="1")
    assert result.returncode != 0
    assert calls == ["npm install"]
