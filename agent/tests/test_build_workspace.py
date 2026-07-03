"""Exercises the REAL build-workspace.sh (the script vestad runs at startup) against
scratch dirs: per-host append-only lineage, tag placement, bundle regeneration."""

import pathlib as pl
import subprocess

from test_workspace_sync import _env, _git  # hermetic-git env helpers

REPO_ROOT = pl.Path(__file__).resolve().parents[2]
BUILD = REPO_ROOT / "vestad/scripts/build-workspace.sh"
BRANCH = "agent-workspace"


def _content(tmp_path, version="0.1.170"):
    """A stand-in extracted agent-code dir, as ensure_agent_code leaves it."""
    content = tmp_path / "agent-code"
    (content / "core").mkdir(parents=True, exist_ok=True)
    (content / "skills/tasks").mkdir(parents=True, exist_ok=True)
    (content / "core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (content / "core/loops.py").write_text(f"# core at {version}\n")
    (content / "skills/tasks/SKILL.md").write_text(f"---\nname: tasks\ndescription: t {version}\n---\n")
    (content / "MEMORY.md").write_text("# memory\n")
    (content / ".gitignore").write_text("data/\nlogs/\n")
    (content / ".vestad-fingerprint").write_text("abc123\n")  # must never be snapshotted
    return content


def _build(tmp_path, content, version):
    ws = tmp_path / "workspace"
    r = subprocess.run(["bash", str(BUILD), str(content), str(ws), version], env=_env(tmp_path), capture_output=True, text=True)
    return ws, r


def test_first_build_creates_repo_tag_and_bundle(tmp_path):
    content = _content(tmp_path)
    ws, r = _build(tmp_path, content, "0.1.170")
    assert r.returncode == 0, r.stdout + r.stderr
    repo = ws / "workspace.git"
    files = _git(["ls-tree", "-r", "--name-only", BRANCH], repo)
    assert "agent/core/pyproject.toml" in files
    assert "agent/skills/tasks/SKILL.md" in files
    assert "agent/MEMORY.md" in files
    assert ".gitignore" in files.splitlines()  # script-owned root scoping file
    assert ".vestad-fingerprint" not in files and "agent/.vestad-fingerprint" not in files
    assert "agent-v0.1.170" in _git(["tag"], repo)
    assert (ws / "workspace.bundle").is_file()


def test_unchanged_content_is_noop(tmp_path):
    content = _content(tmp_path)
    ws, r = _build(tmp_path, content, "0.1.170")
    assert r.returncode == 0
    head = _git(["rev-parse", BRANCH], ws / "workspace.git")
    bundle_before = (ws / "workspace.bundle").read_bytes()
    ws, r = _build(tmp_path, content, "0.1.170")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(["rev-parse", BRANCH], ws / "workspace.git") == head
    assert (ws / "workspace.bundle").read_bytes() == bundle_before


def test_new_version_appends_one_commit_with_new_tag(tmp_path):
    content = _content(tmp_path)
    _build(tmp_path, content, "0.1.170")
    (content / "core/loops.py").write_text("# core at 0.1.171\n")
    (content / "core/pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "0.1.171"\n')
    ws, r = _build(tmp_path, content, "0.1.171")
    assert r.returncode == 0, r.stdout + r.stderr
    repo = ws / "workspace.git"
    log = _git(["log", "--format=%s", BRANCH], repo).splitlines()
    assert log == ["snapshot v0.1.171", "snapshot v0.1.170"]
    tags = _git(["tag"], repo).split()
    assert "agent-v0.1.170" in tags and "agent-v0.1.171" in tags


def test_same_version_content_churn_appends_and_moves_the_tag(tmp_path):
    """Dev flow: content changes while the version stays put; the tag follows the head."""
    content = _content(tmp_path)
    _build(tmp_path, content, "0.1.170")
    (content / "skills/tasks/SKILL.md").write_text("---\nname: tasks\ndescription: dev edit\n---\n")
    ws, r = _build(tmp_path, content, "0.1.170")
    assert r.returncode == 0, r.stdout + r.stderr
    repo = ws / "workspace.git"
    assert len(_git(["log", "--format=%s", BRANCH], repo).splitlines()) == 2
    assert _git(["rev-parse", "agent-v0.1.170"], repo) == _git(["rev-parse", BRANCH], repo)


def test_bundle_is_fetchable_and_carries_branch_plus_tags(tmp_path):
    content = _content(tmp_path)
    ws, _ = _build(tmp_path, content, "0.1.170")
    clone = tmp_path / "clone"
    clone.mkdir()
    _git(["init", "-b", "box"], clone)
    _git(
        ["fetch", "--no-tags", str(ws / "workspace.bundle"),
         "+refs/heads/agent-workspace:refs/remotes/origin/agent-workspace",
         "+refs/tags/agent-v*:refs/tags/agent-v*"],
        clone,
    )
    assert "agent-v0.1.170" in _git(["tag"], clone)
    assert "agent/MEMORY.md" in _git(["ls-tree", "-r", "--name-only", "refs/remotes/origin/agent-workspace"], clone)
