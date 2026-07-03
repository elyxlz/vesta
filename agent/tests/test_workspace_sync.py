"""Exercises the REAL agent-branch box flow against local git repos (no network).

Fixtures build a stand-in published branch with the REAL publish script, then drive the
REAL attach.sh / skills-install / skills-remove scripts plus the documented raw porcelain
(checkpoint + fetch + rebase) in a fake $HOME, pinning the assumptions the fleet relies
on: worktree-safe attach, version-pinned rebase, cone scoping (engine and uninstalled
skills stay off disk), offline installs, downgrades, and the legacy-migration spine.
"""

import os
import pathlib as pl
import shutil
import subprocess

import pytest

AGENT_ROOT = pl.Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_ROOT.parent
PUBLISH = REPO_ROOT / "tools/publish-agent-branch.sh"
ATTACH = AGENT_ROOT / "core/skills/workspace-sync/scripts/attach.sh"
SKILLS_INSTALL = AGENT_ROOT / "skills/skills-registry/scripts/skills-install"
SKILLS_REMOVE = AGENT_ROOT / "skills/skills-registry/scripts/skills-remove"
BRANCH = "agent-workspace"

BASE_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_EDITOR": "true",
}

# These drive real git repos on disk, so they must not be parallelised against each
# other if xdist is ever added. CI runs pytest serially today.
pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("tar") is None, reason="git and tar required")


def _env(home, extra=None):
    e = os.environ.copy()
    e.pop("VESTA_WORKSPACE_REF", None)
    e.update(BASE_ENV)
    e["HOME"] = str(home)
    if extra:
        e.update(extra)
    return e


def _git(args, cwd, extra_env=None):
    r = subprocess.run(["git", *args], cwd=str(cwd), env=_env(cwd, extra_env), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def _run(script, home, args=(), extra_env=None):
    return subprocess.run(["bash", str(script), *args], cwd=str(home), env=_env(home, extra_env), capture_output=True, text=True)


def _publish_fixture(tmp_path, versions=("0.1.170",)):
    """Build origin.git carrying the agent branch with one snapshot per version.
    Returns (origin_path, checkout_path)."""
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", str(origin)], tmp_path)
    src = tmp_path / "checkout"
    src.mkdir()
    _git(["init", "-b", "master"], src)
    _git(["remote", "add", "origin", str(origin)], src)
    for version in versions:
        _write_monorepo_content(src, version)
        _git(["add", "-A"], src)
        _git(["commit", "-m", f"release {version}"], src)
        r = subprocess.run(["bash", str(PUBLISH), "HEAD"], cwd=str(src), env=_env(src), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    return origin, src


def _memory_template(version):
    # Realistic shape: a version-touched header far from the tail agents append to,
    # so a template bump and a local note merge cleanly (as they do in real MEMORY.md).
    return f"# memory template {version}\n\n## About\n\nstable section\n\n## Notes\n\n"


def _write_monorepo_content(src, version):
    (src / "agent/core").mkdir(parents=True, exist_ok=True)
    (src / "agent/core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (src / "agent/core/loops.py").write_text(f"# core at {version}\n")
    for skill in ("tasks", "dream", "whatsapp"):
        d = src / "agent/skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {skill} at {version}\n---\n")
    (src / "agent/MEMORY.md").write_text(_memory_template(version))
    (src / "agent/.gitignore").write_text("data/\nlogs/\n")
    core_scripts = src / "agent/core/skills/workspace-sync/scripts"
    core_scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(ATTACH, core_scripts / "attach.sh")


def _fresh_box(tmp_path, origin, version="0.1.170", skills=("tasks", "dream")):
    """A fake $HOME as the image ships it: snapshot content on disk, no .git."""
    home = tmp_path / "home"
    (home / "agent/core").mkdir(parents=True)
    (home / "agent/core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (home / "agent/core/loops.py").write_text(f"# core at {version}\n")
    for skill in skills:
        d = home / "agent/skills" / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {skill} at {version}\n---\n")
    (home / "agent/MEMORY.md").write_text(_memory_template(version))
    (home / "agent/.gitignore").write_text("data/\nlogs/\n")
    # The image ships the core skills on disk; skills-install shells out to attach.sh
    # at its ~-anchored path.
    core_scripts = home / "agent/core/skills/workspace-sync/scripts"
    core_scripts.mkdir(parents=True)
    shutil.copy(ATTACH, core_scripts / "attach.sh")
    return home


def _box_env(origin):
    return {"VESTA_WORKSPACE_REF": BRANCH, "AGENT_NAME": "testbox", "VESTA_UPSTREAM_URL": str(origin)}


def _attach(home, origin):
    return _run(ATTACH, home, extra_env=_box_env(origin))


def test_fresh_attach_is_clean_and_never_touches_worktree(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    marker = home / "agent/skills/tasks/SKILL.md"
    before = marker.read_text()
    r = _attach(home, origin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == before
    assert _git(["status", "--porcelain"], home, _box_env(origin)) == ""
    assert not (home / "agent/skills/whatsapp").exists()  # not installed -> off disk


def test_attach_is_idempotent(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    assert _attach(home, origin).returncode == 0
    assert _git(["status", "--porcelain"], home, _box_env(origin)) == ""


def test_attach_fails_loudly_when_snapshot_missing(tmp_path):
    origin, _ = _publish_fixture(tmp_path, versions=("0.1.170",))
    home = _fresh_box(tmp_path, origin, version="0.1.999")  # no agent-v0.1.999 published
    r = _attach(home, origin)
    assert r.returncode == 3
    assert not (home / ".git" / "HEAD").exists() or "agent-v0.1.999" in r.stderr


def test_sync_rebases_local_changes_onto_new_snapshot(tmp_path):
    origin, src = _publish_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "my personal notes\n")
    env = _box_env(origin)
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    # Simulate the upgrade: the core mount now runs 0.1.171. Core is mount-owned and
    # out of cone, so this disk change is invisible to git; nothing to commit.
    (home / "agent/core/pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "0.1.171"\n')
    _git(["fetch", "origin"], home, env)
    _git(["rebase", "agent-v0.1.171"], home, env)
    assert "my personal notes" in memory.read_text()
    assert "0.1.171" in (home / "agent/skills/tasks/SKILL.md").read_text()  # upstream moved
    delta = _git(["log", "--format=%s", "agent-v0.1.171..HEAD"], home, env).splitlines()
    assert delta and all(s == "checkpoint" for s in delta)  # my changes on top


def test_sync_conflict_stops_and_continues(tmp_path):
    origin, _ = _publish_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    env = _box_env(origin)
    (home / "agent/skills/tasks/SKILL.md").write_text("mine\n")  # conflicts with 0.1.171's edit
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    _git(["fetch", "origin"], home, env)
    r = subprocess.run(["git", "rebase", "agent-v0.1.171"], cwd=str(home), env=_env(home, env), capture_output=True, text=True)
    assert r.returncode != 0  # conflict markers on disk now
    (home / "agent/skills/tasks/SKILL.md").write_text("both sides survive\n")
    _git(["add", "agent/skills/tasks/SKILL.md"], home, env)
    _git(["rebase", "--continue"], home, env)
    assert "both sides survive" in (home / "agent/skills/tasks/SKILL.md").read_text()


def test_install_is_offline_and_remove_drops_dir(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    shutil.rmtree(origin)  # sever the "network": install must still work from local history
    r = _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=_box_env(origin))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()
    r = _run(SKILLS_REMOVE, home, args=("whatsapp",), extra_env=_box_env(origin))
    assert r.returncode == 0
    assert not (home / "agent/skills/whatsapp").exists()


def test_install_unknown_skill_errors_and_reverts_cone(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    cone_before = _git(["sparse-checkout", "list"], home, _box_env(origin))
    r = _run(SKILLS_INSTALL, home, args=("nope",), extra_env=_box_env(origin))
    assert r.returncode == 1
    assert _git(["sparse-checkout", "list"], home, _box_env(origin)) == cone_before


def test_managed_cone_never_materializes_or_stages_core(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    env = _box_env(origin)
    # core/ exists on disk (the mount provides it) but is out of cone: status ignores it,
    # add -A stages nothing under it.
    (home / "agent/core/loops.py").write_text("# mount content, newer\n")
    assert "agent/core" not in _git(["status", "--porcelain"], home, env)
    _git(["add", "-A"], home, env)
    staged = _git(["diff", "--cached", "--name-only"], home, env)
    assert "agent/core" not in staged


def test_unmanaged_box_pulls_core_updates_through_the_same_rebase(tmp_path):
    origin, _ = _publish_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    env = _box_env(origin)
    _git(["sparse-checkout", "add", "agent/core"], home, env)
    _git(["fetch", "origin"], home, env)
    _git(["rebase", "agent-v0.1.171"], home, env)
    assert "0.1.171" in (home / "agent/core/loops.py").read_text()
    assert "0.1.171" in (home / "agent/core/pyproject.toml").read_text()


def test_downgrade_transplants_delta_onto_older_snapshot(tmp_path):
    origin, _ = _publish_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, origin, version="0.1.171")
    assert _attach(home, origin).returncode == 0
    env = _box_env(origin)
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "keep me\n")
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    _git(["rebase", "--onto", "agent-v0.1.170", "agent-v0.1.171"], home, env)
    assert "keep me" in memory.read_text()
    assert "0.1.170" in (home / "agent/skills/tasks/SKILL.md").read_text()


def test_legacy_workspace_detected_and_migration_spine_converts_it(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    env = _box_env(origin)
    # Fabricate the legacy shape: a repo with old no-cone patterns and stray engine files.
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    (home / "agent/pyproject.toml").write_text("stale\n")
    (home / "agent/MEMORY.md").write_text("# memory template 0.1.170\nmy personal notes\n")
    assert _attach(home, origin).returncode == 4
    # The conversion spine from agent/core/migrations/2026-07-agent-branch-workspace.md:
    (home / ".git").rename(home / ".git-legacy")
    (home / "agent/pyproject.toml").unlink()
    assert _attach(home, origin).returncode == 0
    status = _git(["status", "--porcelain"], home, env)
    assert "agent/MEMORY.md" in status  # personalization surfaced, not lost
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "migrated: local customizations"], home, env)
    assert "my personal notes" in (home / "agent/MEMORY.md").read_text()
