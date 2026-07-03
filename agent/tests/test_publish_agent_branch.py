"""Exercises the REAL publish script against local git repos (no network)."""

import pathlib as pl
import subprocess

from test_upstream_sync import _env  # reuse the hermetic-git env helper (applies BASE_ENV)

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
PUBLISH = REPO_ROOT / "tools/publish-agent-branch.sh"
BRANCH = "agent-workspace"


def _git(args, cwd, extra_env=None):
    r = subprocess.run(["git", *args], cwd=str(cwd), env=_env(cwd, extra_env), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def _make_monorepo(tmp_path, version="0.1.170"):
    """A stand-in monorepo checkout with a bare 'origin' (no network)."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", str(origin)], tmp_path)
    src = tmp_path / "checkout"
    src.mkdir()
    _git(["init", "-b", "master"], src)
    _git(["remote", "add", "origin", str(origin)], src)
    (src / "agent/core").mkdir(parents=True)
    (src / "agent/skills/tasks").mkdir(parents=True)
    (src / "agent/core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (src / "agent/core/main.py").write_text("print('core')\n")
    (src / "agent/skills/tasks/SKILL.md").write_text("---\nname: tasks\ndescription: t\n---\n")
    (src / "agent/MEMORY.md").write_text("# memory\n")
    (src / "agent/.gitignore").write_text("data/\nlogs/\n")
    (src / "vestad").mkdir()
    (src / "vestad/main.rs").write_text("// never published\n")
    (src / ".claude").mkdir()
    (src / ".claude/settings.json").write_text("{}\n")
    _git(["add", "-A"], src)
    _git(["commit", "-m", "seed"], src)
    _git(["push", "origin", "master"], src)
    return src, origin


def _publish(src, ref="HEAD"):
    return subprocess.run(["bash", str(PUBLISH), ref], cwd=str(src), env=_env(src), capture_output=True, text=True)


def _bump(src, version):
    (src / "agent/core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (src / "agent/skills/tasks/SKILL.md").write_text(f"---\nname: tasks\ndescription: t {version}\n---\n")
    _git(["add", "-A"], src)
    _git(["commit", "-m", f"release {version}"], src)


def test_bootstrap_publish_creates_branch_and_tag_with_filtered_content(tmp_path):
    src, origin = _make_monorepo(tmp_path)
    r = _publish(src)
    assert r.returncode == 0, r.stdout + r.stderr
    files = _git(["ls-tree", "-r", "--name-only", BRANCH], origin)
    assert "agent/core/pyproject.toml" in files
    assert "agent/skills/tasks/SKILL.md" in files
    assert "agent/MEMORY.md" in files
    assert ".gitignore" in files.splitlines()  # workflow-owned root ignore
    assert "vestad/main.rs" not in files
    assert ".claude/settings.json" not in files
    assert "agent-v0.1.170" in _git(["tag"], origin)


def test_republish_same_content_is_noop(tmp_path):
    src, origin = _make_monorepo(tmp_path)
    assert _publish(src).returncode == 0
    before = _git(["rev-parse", BRANCH], origin)
    assert _publish(src).returncode == 0
    assert _git(["rev-parse", BRANCH], origin) == before


def test_new_release_appends_exactly_one_commit(tmp_path):
    src, origin = _make_monorepo(tmp_path)
    assert _publish(src).returncode == 0
    _bump(src, "0.1.171")
    assert _publish(src).returncode == 0
    log = _git(["log", "--format=%s", BRANCH], origin).splitlines()
    assert len(log) == 2 and log[0].startswith("publish v0.1.171")
    assert "agent-v0.1.171" in _git(["tag"], origin)


def test_refuses_non_fast_forward(tmp_path):
    src, origin = _make_monorepo(tmp_path)
    assert _publish(src).returncode == 0
    # Someone rewrites the remote branch behind our back.
    _git(["update-ref", f"refs/heads/{BRANCH}", "master"], origin)
    _bump(src, "0.1.171")
    r = _publish(src)
    assert r.returncode != 0
