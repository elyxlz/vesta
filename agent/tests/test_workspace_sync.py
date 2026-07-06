"""Exercises the REAL box workspace flow against local workspace bundles (no network).

Fixtures build a bundle with the REAL build-workspace.sh (the script vestad runs), then
drive the REAL attach.sh / fetch-workspace.sh / skills-install / skills-remove scripts plus
the documented raw porcelain (checkpoint + fetch + rebase) in a fake $HOME, pinning the
assumptions the fleet relies on: worktree-safe attach, version-pinned rebase, cone scoping
(engine and uninstalled skills stay off disk), offline installs, downgrades, and the
legacy-migration spine.
"""

import os
import pathlib as pl
import shutil
import subprocess

import pytest

AGENT_ROOT = pl.Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_ROOT.parent
BUILD = REPO_ROOT / "vestad/scripts/build-workspace.sh"
ATTACH = AGENT_ROOT / "core/skills/workspace-sync/scripts/attach.sh"
FETCH = AGENT_ROOT / "core/skills/workspace-sync/scripts/fetch-workspace.sh"
SET_CONE = AGENT_ROOT / "core/skills/workspace-sync/scripts/set-cone.sh"
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
    e.pop("VESTA_WORKSPACE_BUNDLE", None)
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


def _memory_template(version):
    # Realistic shape: a version-touched header far from the tail agents append to,
    # so a template bump and a local note merge cleanly (as they do in real MEMORY.md).
    return f"# memory template {version}\n\n## About\n\nstable section\n\n## Notes\n\n"


def _write_content(content, version):
    """A stand-in extracted agent-code dir, as ensure_agent_code leaves it."""
    (content / "core").mkdir(parents=True, exist_ok=True)
    (content / "core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (content / "core/loops.py").write_text(f"# core at {version}\n")
    for skill in ("tasks", "dream", "whatsapp"):
        d = content / "skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {skill} at {version}\n---\n")
    (content / "MEMORY.md").write_text(_memory_template(version))
    (content / ".gitignore").write_text((AGENT_ROOT / ".gitignore").read_text())
    (content / "ruff.toml").write_text("line-length = 144\n")  # box needs it (formatting); ships in the snapshot
    core_scripts = content / "core/skills/workspace-sync/scripts"
    core_scripts.mkdir(parents=True, exist_ok=True)
    shutil.copy(ATTACH, core_scripts / "attach.sh")
    shutil.copy(FETCH, core_scripts / "fetch-workspace.sh")
    shutil.copy(SET_CONE, core_scripts / "set-cone.sh")


def _bundle_fixture(tmp_path, versions=("0.1.170",)):
    """Build a workspace bundle with the REAL build-workspace.sh, one snapshot per version.
    Returns the bundle path (what a box's fetch-workspace.sh consumes)."""
    content = tmp_path / "agent-code"
    ws = tmp_path / "workspace"
    for version in versions:
        _write_content(content, version)
        r = subprocess.run(["bash", str(BUILD), str(content), str(ws), version], env=_env(tmp_path), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    return ws / "workspace.bundle"


def _fresh_box(tmp_path, version="0.1.170", skills=("tasks", "dream"), managed=True):
    """A fake $HOME as the image ships it: snapshot content on disk, no .git.

    managed=True models the read-only core mount: agent/core dirs are unwritable, so git
    cone updates warn instead of pruning core (the contract real boxes rely on). Pass
    managed=False for unmanaged boxes, whose core lives writable in the workspace."""
    home = tmp_path / "home"
    (home / "agent/core").mkdir(parents=True)
    (home / "agent/core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (home / "agent/core/loops.py").write_text(f"# core at {version}\n")
    for skill in skills:
        d = home / "agent/skills" / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {skill} at {version}\n---\n")
    (home / "agent/MEMORY.md").write_text(_memory_template(version))
    (home / "agent/.gitignore").write_text((AGENT_ROOT / ".gitignore").read_text())
    (home / "agent/constitution.md").write_text("# user rules\n")  # bind-mounted read-only on real boxes
    (home / "agent/ruff.toml").write_text("line-length = 144\n")  # shipped in the image; tracked, must stay clean
    # The image ships the core skills on disk; skills-install and the sync flow shell out
    # to attach.sh / fetch-workspace.sh at their ~-anchored paths.
    core_scripts = home / "agent/core/skills/workspace-sync/scripts"
    core_scripts.mkdir(parents=True)
    shutil.copy(ATTACH, core_scripts / "attach.sh")
    shutil.copy(FETCH, core_scripts / "fetch-workspace.sh")
    shutil.copy(SET_CONE, core_scripts / "set-cone.sh")
    if managed:
        core = home / "agent/core"
        for d in [core, *(p for p in core.rglob("*") if p.is_dir())]:
            d.chmod(0o555)
    return home


def _box_env(bundle):
    return {"VESTA_WORKSPACE_BUNDLE": str(bundle), "AGENT_NAME": "testbox"}


def _attach(home, bundle):
    return _run(ATTACH, home, extra_env=_box_env(bundle))


def test_fresh_attach_is_clean_and_never_touches_worktree(tmp_path):
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    marker = home / "agent/skills/tasks/SKILL.md"
    before = marker.read_text()
    r = _attach(home, bundle)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == before
    assert _git(["status", "--porcelain"], home, _box_env(bundle)) == ""
    assert not (home / "agent/skills/whatsapp").exists()  # not installed -> off disk


def test_attach_is_idempotent(tmp_path):
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, bundle).returncode == 0
    assert _attach(home, bundle).returncode == 0
    assert _git(["status", "--porcelain"], home, _box_env(bundle)) == ""


def test_attach_fails_loudly_when_snapshot_missing(tmp_path):
    bundle = _bundle_fixture(tmp_path, versions=("0.1.170",))
    home = _fresh_box(tmp_path, version="0.1.999")  # no agent-v0.1.999 in the bundle
    r = _attach(home, bundle)
    assert r.returncode == 3
    assert not (home / ".git" / "HEAD").exists() or "agent-v0.1.999" in r.stderr


def test_sync_rebases_local_changes_onto_new_snapshot(tmp_path):
    bundle = _bundle_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path)
    assert _attach(home, bundle).returncode == 0
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "my personal notes\n")
    env = _box_env(bundle)
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    # Simulate the upgrade: the core mount now runs 0.1.171. Core is mount-owned and
    # out of cone, so this disk change is invisible to git; nothing to commit.
    (home / "agent/core/pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "0.1.171"\n')
    r = _run(FETCH, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    _git(["rebase", "agent-v0.1.171"], home, env)
    assert "my personal notes" in memory.read_text()
    assert "0.1.171" in (home / "agent/skills/tasks/SKILL.md").read_text()  # stock moved
    delta = _git(["log", "--format=%s", "agent-v0.1.171..HEAD"], home, env).splitlines()
    assert delta and all(s == "checkpoint" for s in delta)  # my changes on top


def test_sync_conflict_stops_and_continues(tmp_path):
    bundle = _bundle_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path)
    assert _attach(home, bundle).returncode == 0
    env = _box_env(bundle)
    (home / "agent/skills/tasks/SKILL.md").write_text("mine\n")  # conflicts with 0.1.171's edit
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    assert _run(FETCH, home, extra_env=env).returncode == 0
    r = subprocess.run(["git", "rebase", "agent-v0.1.171"], cwd=str(home), env=_env(home, env), capture_output=True, text=True)
    assert r.returncode != 0  # conflict markers on disk now
    (home / "agent/skills/tasks/SKILL.md").write_text("both sides survive\n")
    _git(["add", "agent/skills/tasks/SKILL.md"], home, env)
    _git(["rebase", "--continue"], home, env)
    assert "both sides survive" in (home / "agent/skills/tasks/SKILL.md").read_text()


def test_install_is_offline_and_remove_drops_dir(tmp_path):
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, bundle).returncode == 0
    bundle.unlink()  # sever the source: install must still work from local history
    r = _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=_box_env(bundle))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()
    r = _run(SKILLS_REMOVE, home, args=("whatsapp",), extra_env=_box_env(bundle))
    assert r.returncode == 0
    assert not (home / "agent/skills/whatsapp").exists()


def test_install_unknown_skill_errors_and_reverts_cone(tmp_path):
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, bundle).returncode == 0
    cone_before = _git(["sparse-checkout", "list"], home, _box_env(bundle))
    r = _run(SKILLS_INSTALL, home, args=("nope",), extra_env=_box_env(bundle))
    assert r.returncode == 1
    assert _git(["sparse-checkout", "list"], home, _box_env(bundle)) == cone_before


def _commit_user_dir(home, env, path="agent/prompts/restart.md", body="my daemon block\n"):
    """An agent versioning its own directory under agent/, as the conversion migration
    instructs (git add -A && commit). Returns the file path."""
    file = home / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(body)
    _git(["add", "-A", "--sparse"], home, env)  # new dirs start out-of-cone; the documented flow
    _git(["commit", "-m", "my customizations"], home, env)
    return file


def test_committed_agent_dirs_join_cone_and_survive_reapply(tmp_path):
    """Issue #979: tracked dirs under agent/ outside the skills cone were pruned by any
    sparse-checkout reapply. set-cone.sh derives the cone from the tracked tree, so a
    committed dir survives."""
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(bundle)
    assert _attach(home, bundle).returncode == 0
    restart = _commit_user_dir(home, env)
    scripts = _commit_user_dir(home, env, path="agent/scripts/state-server.py", body="print()\n")
    r = _run(SET_CONE, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    cone = _git(["sparse-checkout", "list"], home, env).splitlines()
    assert "agent/prompts" in cone and "agent/scripts" in cone
    _git(["sparse-checkout", "reapply"], home, env)
    assert restart.read_text() == "my daemon block\n"
    assert scripts.exists()


def test_install_and_remove_preserve_committed_agent_dirs(tmp_path):
    """A dir committed after the last cone computation must not be pruned when
    skills-install/skills-remove rewrite the cone."""
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(bundle)
    assert _attach(home, bundle).returncode == 0
    restart = _commit_user_dir(home, env)
    r = _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()
    assert restart.exists()
    r = _run(SKILLS_REMOVE, home, args=("whatsapp",), extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (home / "agent/skills/whatsapp").exists()
    assert restart.exists()


def test_reattach_preserves_user_dirs_and_unmanaged_core(tmp_path):
    """Re-running attach.sh (idempotence promise) must keep tracked agent dirs and an
    unmanaged box's one-time agent/core opt-in in the cone."""
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(bundle)
    assert _attach(home, bundle).returncode == 0
    _git(["sparse-checkout", "add", "agent/core"], home, env)  # SETUP.md: once, ever
    restart = _commit_user_dir(home, env)
    r = _attach(home, bundle)
    assert r.returncode == 0, r.stdout + r.stderr
    cone = _git(["sparse-checkout", "list"], home, env).splitlines()
    assert "agent/core" in cone and "agent/prompts" in cone
    assert restart.exists()


def test_managed_cone_never_materializes_or_stages_core(tmp_path):
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, bundle).returncode == 0
    env = _box_env(bundle)
    # core/ exists on disk (the mount provides it) but is out of cone: status ignores it,
    # add -A stages nothing under it.
    (home / "agent/core/loops.py").write_text("# mount content, newer\n")
    assert "agent/core" not in _git(["status", "--porcelain"], home, env)
    _git(["add", "-A"], home, env)
    staged = _git(["diff", "--cached", "--name-only"], home, env)
    assert "agent/core" not in staged


def test_unmanaged_box_pulls_core_updates_through_the_same_rebase(tmp_path):
    bundle = _bundle_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, managed=False)
    assert _attach(home, bundle).returncode == 0
    env = _box_env(bundle)
    _git(["sparse-checkout", "add", "agent/core"], home, env)
    assert _run(FETCH, home, extra_env=env).returncode == 0
    _git(["rebase", "agent-v0.1.171"], home, env)
    assert "0.1.171" in (home / "agent/core/loops.py").read_text()
    assert "0.1.171" in (home / "agent/core/pyproject.toml").read_text()


def test_downgrade_transplants_delta_onto_older_snapshot(tmp_path):
    bundle = _bundle_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, version="0.1.171")
    assert _attach(home, bundle).returncode == 0
    env = _box_env(bundle)
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "keep me\n")
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    _git(["rebase", "--onto", "agent-v0.1.170", "agent-v0.1.171"], home, env)
    assert "keep me" in memory.read_text()
    assert "0.1.170" in (home / "agent/skills/tasks/SKILL.md").read_text()


def test_legacy_workspace_detected_and_migration_spine_converts_it(tmp_path):
    bundle = _bundle_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(bundle)
    # Fabricate the legacy shape: a repo with old no-cone patterns and stray engine files.
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    (home / "agent/pyproject.toml").write_text("stale\n")
    (home / "agent/MEMORY.md").write_text("# memory template 0.1.170\nmy personal notes\n")
    assert _attach(home, bundle).returncode == 4
    # The conversion spine from agent/core/migrations/2026-07-workspace-conversion.md:
    (home / ".git").rename(home / ".git-legacy")
    (home / "agent/pyproject.toml").unlink()
    assert _attach(home, bundle).returncode == 0
    status = _git(["status", "--porcelain"], home, env)
    assert "agent/MEMORY.md" in status  # personalization surfaced, not lost
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "my customizations"], home, env)
    assert "my personal notes" in (home / "agent/MEMORY.md").read_text()


def test_migration_restores_legacy_repo_when_snapshot_unavailable(tmp_path):
    """An unmanaged legacy box at a version the bundle doesn't carry (its snapshot predates
    the workspace feature) must never be left repo-less: the documented spine restores the
    old repo when the conversion attach fails, so git still works and the box degrades
    gracefully instead of bricking."""
    bundle = _bundle_fixture(tmp_path, versions=("0.1.170",))
    home = _fresh_box(tmp_path, version="0.1.999")  # 0.1.999 is not in the bundle
    env = _box_env(bundle)
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    assert _attach(home, bundle).returncode == 4  # legacy detected

    # Spine step 2: retire, attach (fails exit 3 — no agent-v0.1.999), then restore.
    (home / ".git").rename(home / ".git-legacy")
    assert _attach(home, bundle).returncode == 3
    shutil.rmtree(home / ".git")  # drop the half-made repo the failed attach left
    (home / ".git-legacy").rename(home / ".git")

    # The box still has a working repo (not bricked), and it's the legacy one.
    assert _git(["rev-parse", "--is-inside-work-tree"], home, env).strip() == "true"
    assert (home / ".git/info/sparse-checkout").exists()
    assert not (home / ".git-legacy").exists()
