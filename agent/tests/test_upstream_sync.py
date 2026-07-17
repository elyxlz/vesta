"""Exercises the REAL box workspace flow against local upstream repos (no network).

Fixtures build an upstream repo with the REAL build-upstream.sh (the script vestad runs),
then drive the REAL attach.sh / fetch-upstream.sh / skills-install / skills-remove scripts plus
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
BUILD = REPO_ROOT / "vestad/scripts/build-upstream.sh"
ATTACH = AGENT_ROOT / "core/skills/upstream-sync/scripts/attach.sh"
FETCH = AGENT_ROOT / "core/skills/upstream-sync/scripts/fetch-upstream.sh"
SET_CONE = AGENT_ROOT / "core/skills/upstream-sync/scripts/set-cone.sh"
SYNC = AGENT_ROOT / "core/skills/upstream-sync/scripts/sync.sh"
STATUS = AGENT_ROOT / "core/skills/upstream-sync/scripts/status.sh"
SKILLS_INSTALL = AGENT_ROOT / "skills/skills-registry/scripts/skills-install"
SKILLS_REMOVE = AGENT_ROOT / "skills/skills-registry/scripts/skills-remove"
BRANCH = "agent-upstream"
# LEGACY(remove-when: no agent predating the rename release remains): the forwarding
# shims old boxes' synced scripts and released migrations rely on.
FORWARDING = AGENT_ROOT / "core/skills/workspace-sync/scripts"

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
    e.pop("VESTA_UPSTREAM_SOURCE", None)
    e.update(BASE_ENV)
    e["HOME"] = str(home)
    if extra:
        e.update(extra)
    return e


def _git(args, cwd, extra_env=None):
    r = subprocess.run(["git", *args], cwd=str(cwd), env=_env(cwd, extra_env), capture_output=True, text=True, check=False)
    assert r.returncode == 0, f"git {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def _run(script, home, args=(), extra_env=None):
    return subprocess.run(["bash", str(script), *args], cwd=str(home), env=_env(home, extra_env), capture_output=True, text=True, check=False)


def _copy_sync_scripts(core_skills):
    """The upstream-sync scripts a box ships in agent/core (one owner for the list),
    plus the forwarding workspace-sync shims at their old paths."""
    scripts = core_skills / "upstream-sync/scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for script in (ATTACH, FETCH, SET_CONE, SYNC, STATUS):
        shutil.copy(script, scripts / script.name)
    forwarding = core_skills / "workspace-sync/scripts"
    forwarding.mkdir(parents=True, exist_ok=True)
    for shim in FORWARDING.glob("*.sh"):
        shutil.copy(shim, forwarding / shim.name)


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
    _copy_sync_scripts(content / "core/skills")


def _upstream_fixture(tmp_path, versions=("0.1.170",), new_dir=None):
    """Build an upstream repo with the REAL build-upstream.sh, one snapshot per version.
    Returns the bare repo path (what a box's fetch-upstream.sh consumes; on real boxes it
    is bind-mounted at /run/vesta-upstream/upstream.git). new_dir models a release adding a
    tracked dir under agent/: it lands in the last version's snapshot only."""
    content = tmp_path / "agent-code"
    ws = tmp_path / "upstream"
    for version in versions:
        _write_content(content, version)
        if new_dir is not None and version == versions[-1]:
            (content / new_dir).mkdir(parents=True, exist_ok=True)
            (content / new_dir / "stock.md").write_text(f"{new_dir} at {version}\n")
        r = subprocess.run(
            ["bash", str(BUILD), str(content), str(ws), version], env=_env(tmp_path), capture_output=True, text=True, check=False
        )
        assert r.returncode == 0, r.stdout + r.stderr
    return ws / "upstream.git"


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
    # to attach.sh / fetch-upstream.sh at their ~-anchored paths.
    _copy_sync_scripts(home / "agent/core/skills")
    if managed:
        core = home / "agent/core"
        for d in [core, *(p for p in core.rglob("*") if p.is_dir())]:
            d.chmod(0o555)
    return home


def _upgrade_core_mount(home, version):
    """vestad swapping a managed box's engine: the core mount now carries the new version,
    still read-only (modelled with chmod, so git's unlink fails EACCES where a real bind
    mount gives EROFS; nothing under test keys on the errno)."""
    core = home / "agent/core"
    dirs = [core, *(p for p in core.rglob("*") if p.is_dir())]
    for d in dirs:
        d.chmod(0o755)
    (core / "pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (core / "loops.py").write_text(f"# core at {version}\n")
    for d in dirs:
        d.chmod(0o555)


def _box_env(source):
    return {"VESTA_UPSTREAM_SOURCE": str(source), "AGENT_NAME": "testbox"}


def _attach(home, source):
    return _run(ATTACH, home, extra_env=_box_env(source))


def test_fresh_attach_is_clean_and_never_touches_worktree(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    marker = home / "agent/skills/tasks/SKILL.md"
    before = marker.read_text()
    r = _attach(home, source)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == before
    assert _git(["status", "--porcelain"], home, _box_env(source)) == ""
    assert not (home / "agent/skills/whatsapp").exists()  # not installed -> off disk


def test_attach_is_idempotent(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    assert _attach(home, source).returncode == 0
    assert _git(["status", "--porcelain"], home, _box_env(source)) == ""


def test_attach_fails_loudly_when_snapshot_missing(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170",))
    home = _fresh_box(tmp_path, version="0.1.999")  # no agent-v0.1.999 in the upstream repo
    r = _attach(home, source)
    assert r.returncode == 3
    assert not (home / ".git" / "HEAD").exists() or "agent-v0.1.999" in r.stderr


def test_sync_rebases_local_changes_onto_new_snapshot(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "my personal notes\n")
    env = _box_env(source)
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
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    env = _box_env(source)
    (home / "agent/skills/tasks/SKILL.md").write_text("mine\n")  # conflicts with 0.1.171's edit
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    assert _run(FETCH, home, extra_env=env).returncode == 0
    r = subprocess.run(["git", "rebase", "agent-v0.1.171"], cwd=str(home), env=_env(home, env), capture_output=True, text=True, check=False)
    assert r.returncode != 0  # conflict markers on disk now
    (home / "agent/skills/tasks/SKILL.md").write_text("both sides survive\n")
    _git(["add", "agent/skills/tasks/SKILL.md"], home, env)
    _git(["rebase", "--continue"], home, env)
    assert "both sides survive" in (home / "agent/skills/tasks/SKILL.md").read_text()


def _legacy_managed_box(tmp_path, new_dir=None):
    """A managed box in the shape issue #1280 reports: the engine is a read-only mount, but
    agent/core is in the cone and its own commits carry engine paths (how pre-mount boxes
    converged). Every later checkout then wants to rewrite the mount."""
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"), new_dir=new_dir)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    _git(["sparse-checkout", "add", "agent/core"], home, env)
    engine = home / "agent/core/loops.py"
    engine.chmod(0o644)
    engine.write_text("# core at 0.1.170\n# a stale engine edit my history carries\n")
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "my personal notes\n")
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    _upgrade_core_mount(home, "0.1.171")
    return source, home, env


def test_managed_sync_lands_when_history_carries_engine_paths(tmp_path):
    """Issue #1280: rebasing engine paths onto the new snapshot fails because the core mount
    is read-only, so the sync never completed and the boot turn re-fired forever. sync.sh
    drops the mount-owned paths from the local delta, so the rebase lands."""
    _source, home, env = _legacy_managed_box(tmp_path)
    r = _run(SYNC, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    _git(["merge-base", "--is-ancestor", "agent-v0.1.171", "HEAD"], home, env)  # what the boot turn re-fires on
    assert "my personal notes" in (home / "agent/MEMORY.md").read_text()  # my work survives
    assert "0.1.171" in (home / "agent/skills/tasks/SKILL.md").read_text()  # stock moved
    # The mount is untouched, and git now records stock's engine rather than the stale edit.
    assert (home / "agent/core/loops.py").read_text() == "# core at 0.1.171\n"
    tracked_engine = _git(["ls-tree", "-r", "HEAD", "--", "agent/core"], home, env)
    assert tracked_engine == _git(["ls-tree", "-r", "agent-v0.1.171", "--", "agent/core"], home, env)


def test_managed_sync_materializes_a_dir_the_new_snapshot_adds(tmp_path):
    """The cone is computed from HEAD, so set-cone.sh has to run after the rebase too: a dir
    the upgrade adds is only coned in, and written to disk, once the rebase has landed it."""
    _source, home, env = _legacy_managed_box(tmp_path, new_dir="prompts")
    assert _run(SYNC, home, extra_env=env).returncode == 0
    assert (home / "agent/prompts/stock.md").read_text() == "prompts at 0.1.171\n"


def test_managed_sync_is_idempotent_once_synced(tmp_path):
    """The re-fire loop's cost was re-running a rebase that could not work. A second sync is
    a no-op that reports the authoritative answer instead."""
    _source, home, env = _legacy_managed_box(tmp_path)
    assert _run(SYNC, home, extra_env=env).returncode == 0
    head = _git(["rev-parse", "HEAD"], home, env)
    r = _run(SYNC, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already synced" in r.stdout
    assert _git(["rev-parse", "HEAD"], home, env) == head


def test_managed_cone_pins_engine_out_of_the_worktree(tmp_path):
    """The mechanism: git cannot sparsify the engine (that means deleting read-only files),
    so set-cone.sh sets skip-worktree straight in the index. Without it every checkout of a
    new snapshot tries to rewrite the mount."""
    _source, home, env = _legacy_managed_box(tmp_path)
    assert _run(SET_CONE, home, extra_env=env).returncode == 0
    flags = _git(["ls-files", "-v", "--", "agent/core"], home, env).splitlines()
    assert flags and all(line.startswith("S ") for line in flags), flags
    assert _git(["status", "--porcelain"], home, env) == ""  # mount drift is invisible to git


def test_unmanaged_core_still_rebases_through_the_cone(tmp_path):
    """--no-manage-core-code boxes own agent/core in the workspace and legitimately pull the
    engine through the rebase: it must stay worktree-live, never pinned."""
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, managed=False)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    _git(["sparse-checkout", "add", "agent/core"], home, env)  # SETUP.md: the one-time opt-in
    assert _run(SET_CONE, home, extra_env=env).returncode == 0
    flags = _git(["ls-files", "-v", "--", "agent/core"], home, env).splitlines()
    assert flags and not any(line.startswith("S ") for line in flags), flags
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "my personal notes\n")
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    assert _run(FETCH, home, extra_env=env).returncode == 0
    _git(["rebase", "agent-v0.1.171"], home, env)
    assert (home / "agent/core/loops.py").read_text() == "# core at 0.1.171\n"  # engine advanced on disk
    assert "my personal notes" in memory.read_text()


def test_status_reports_the_authoritative_sync_answer(tmp_path):
    """status.sh grouped commits under "my changes on top of <tag>" either way, which reads
    like a finished sync when the rebase never landed (issue #1280)."""
    _source, home, env = _legacy_managed_box(tmp_path)
    r = _run(STATUS, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT synced" in r.stdout
    assert _run(SYNC, home, extra_env=env).returncode == 0
    r = _run(STATUS, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT synced" not in r.stdout and "== synced" in r.stdout


def test_install_is_offline_and_remove_drops_dir(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    shutil.rmtree(source)  # sever the source: install must still work from local history
    r = _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=_box_env(source))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()
    r = _run(SKILLS_REMOVE, home, args=("whatsapp",), extra_env=_box_env(source))
    assert r.returncode == 0
    assert not (home / "agent/skills/whatsapp").exists()


def test_install_unknown_skill_errors_and_leaves_cone_untouched(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    cone_before = _git(["sparse-checkout", "list"], home, _box_env(source))
    r = _run(SKILLS_INSTALL, home, args=("nope",), extra_env=_box_env(source))
    assert r.returncode == 1
    assert _git(["sparse-checkout", "list"], home, _box_env(source)) == cone_before


def _commit_user_dir(home, env, path="agent/prompts/restart.md", body="my daemon block\n"):
    """An agent versioning its own directory under agent/, as the conversion migration
    instructs (git add -A --sparse && commit). Returns the file path."""
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
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
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
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
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
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path, managed=False)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    _git(["sparse-checkout", "add", "agent/core"], home, env)  # SETUP.md: once, ever
    restart = _commit_user_dir(home, env)
    r = _attach(home, source)
    assert r.returncode == 0, r.stdout + r.stderr
    cone = _git(["sparse-checkout", "list"], home, env).splitlines()
    assert "agent/core" in cone and "agent/prompts" in cone
    assert restart.exists()


def test_remove_last_skill_refuses_instead_of_emptying_cone(tmp_path):
    """An empty cone would prune every tracked file under agent/ (MEMORY.md included);
    removing the last skill must fail loudly, not report success."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path, skills=("tasks",))
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    r = _run(SKILLS_REMOVE, home, args=("tasks",), extra_env=env)
    assert r.returncode != 0
    assert (home / "agent/MEMORY.md").exists()
    assert (home / "agent/skills/tasks/SKILL.md").exists()


def test_removed_dirty_skill_errors_and_stays_out_of_the_cone(tmp_path):
    """git leaves a skill dir behind when it holds uncommitted edits: remove must say so
    (the skill stays active), and later recomputes must not resurrect the cone entry."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    (home / "agent/skills/dream/SKILL.md").write_text("my personalization\n")  # uncommitted
    r = _run(SKILLS_REMOVE, home, args=("dream",), extra_env=env)
    assert r.returncode != 0
    assert "still on disk" in r.stderr
    r = _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=env)  # any later recompute
    assert r.returncode == 0, r.stdout + r.stderr
    assert "agent/skills/dream" not in _git(["sparse-checkout", "list"], home, env).splitlines()


def test_stray_core_cone_entry_on_managed_box_heals(tmp_path):
    """agent/core in the cone of a managed box (read-only mount) is a mistake; the next
    recompute must drop it rather than perpetuate it."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    _git(["sparse-checkout", "add", "agent/core"], home, env)  # the stray
    r = _run(SET_CONE, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "agent/core" not in _git(["sparse-checkout", "list"], home, env).splitlines()


def test_committed_root_dir_survives_recompute(tmp_path):
    """A force-added tracked dir at the workspace root (outside agent/) must stay coned."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    note = home / "notes/n.md"
    note.parent.mkdir()
    note.write_text("keep\n")
    _git(["add", "--sparse", "-f", "notes/n.md"], home, env)  # root .gitignore excludes non-agent
    _git(["commit", "-m", "my notes"], home, env)
    r = _run(SET_CONE, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    _git(["sparse-checkout", "reapply"], home, env)
    assert note.read_text() == "keep\n"


def test_set_cone_refuses_legacy_workspace(tmp_path):
    """A legacy no-cone sparse file must not be force-converted by a cone recompute; the
    boot migration owns that conversion."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    r = _run(SET_CONE, home, extra_env=env)
    assert r.returncode == 4
    assert "legacy" in r.stderr


def test_managed_cone_never_materializes_or_stages_core(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    env = _box_env(source)
    # core/ exists on disk (the mount provides it) but is out of cone: status ignores it,
    # add -A stages nothing under it.
    (home / "agent/core/loops.py").write_text("# mount content, newer\n")
    assert "agent/core" not in _git(["status", "--porcelain"], home, env)
    _git(["add", "-A"], home, env)
    staged = _git(["diff", "--cached", "--name-only"], home, env)
    assert "agent/core" not in staged


def test_unmanaged_box_pulls_core_updates_through_the_same_rebase(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, managed=False)
    assert _attach(home, source).returncode == 0
    env = _box_env(source)
    _git(["sparse-checkout", "add", "agent/core"], home, env)
    assert _run(FETCH, home, extra_env=env).returncode == 0
    _git(["rebase", "agent-v0.1.171"], home, env)
    assert "0.1.171" in (home / "agent/core/loops.py").read_text()
    assert "0.1.171" in (home / "agent/core/pyproject.toml").read_text()


def test_downgrade_transplants_delta_onto_older_snapshot(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, version="0.1.171")
    assert _attach(home, source).returncode == 0
    env = _box_env(source)
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "keep me\n")
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    _git(["rebase", "--onto", "agent-v0.1.170", "agent-v0.1.171"], home, env)
    assert "keep me" in memory.read_text()
    assert "0.1.170" in (home / "agent/skills/tasks/SKILL.md").read_text()


def test_legacy_workspace_detected_and_migration_spine_converts_it(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    # Fabricate the legacy shape: a repo with old no-cone patterns and stray engine files.
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    (home / "agent/pyproject.toml").write_text("stale\n")
    (home / "agent/MEMORY.md").write_text("# memory template 0.1.170\nmy personal notes\n")
    assert _attach(home, source).returncode == 4
    # The conversion spine from agent/core/migrations/2026-07-workspace-conversion.md:
    (home / ".git").rename(home / ".git-legacy")
    (home / "agent/pyproject.toml").unlink()
    assert _attach(home, source).returncode == 0
    status = _git(["status", "--porcelain"], home, env)
    assert "agent/MEMORY.md" in status  # personalization surfaced, not lost
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "my customizations"], home, env)
    assert "my personal notes" in (home / "agent/MEMORY.md").read_text()


def test_migration_restores_legacy_repo_when_snapshot_unavailable(tmp_path):
    """An unmanaged legacy box at a version the upstream doesn't carry (its snapshot predates
    the workspace feature) must never be left repo-less: the documented spine restores the
    old repo when the conversion attach fails, so git still works and the box degrades
    gracefully instead of bricking."""
    source = _upstream_fixture(tmp_path, versions=("0.1.170",))
    home = _fresh_box(tmp_path, version="0.1.999")  # 0.1.999 is not in the upstream repo
    env = _box_env(source)
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    assert _attach(home, source).returncode == 4  # legacy detected

    # Spine step 2: retire, attach (fails exit 3 — no agent-v0.1.999), then restore.
    (home / ".git").rename(home / ".git-legacy")
    assert _attach(home, source).returncode == 3
    shutil.rmtree(home / ".git")  # drop the half-made repo the failed attach left
    (home / ".git-legacy").rename(home / ".git")

    # The box still has a working repo (not bricked), and it's the legacy one.
    assert _git(["rev-parse", "--is-inside-work-tree"], home, env).strip() == "true"
    assert (home / ".git/info/sparse-checkout").exists()
    assert not (home / ".git-legacy").exists()


def test_fetch_from_the_legacy_bundle_lands_the_same_refs(tmp_path):
    """LEGACY(remove-when: no agent predating the rename release remains): old boxes fetch
    the bundle the endpoint serves; it must carry the same snapshot as the bare repo."""
    source = _upstream_fixture(tmp_path)
    bundle = source.parent / "workspace.bundle"
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    via_repo = _git(["rev-parse", "refs/tags/agent-v0.1.170"], home, _box_env(source)).strip()
    other = tmp_path / "home2"
    other.mkdir()
    _git(["init", "-b", "otherbox"], other)
    r = _run(FETCH, other, extra_env={"VESTA_UPSTREAM_SOURCE": str(bundle), "AGENT_NAME": "otherbox"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(["rev-parse", "refs/tags/agent-v0.1.170"], other).strip() == via_repo


def test_forwarding_workspace_sync_scripts_behave_identically(tmp_path):
    """LEGACY(remove-when: no agent predating the rename release remains): released
    migrations call the old script paths verbatim; the shims must forward."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    shim_attach = home / "agent/core/skills/workspace-sync/scripts/attach.sh"
    r = _run(shim_attach, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(["status", "--porcelain"], home, env) == ""
    r = _run(home / "agent/core/skills/workspace-sync/scripts/fetch-workspace.sh", home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(["rev-parse", "refs/remotes/upstream/agent-upstream"], home, env).strip()


def test_fetch_without_mount_falls_into_the_endpoint_fallback(tmp_path):
    """LEGACY(remove-when: no agent predating the rename release remains): a pre-rename
    container has no /run/vesta-upstream; fetch must take the bundle-endpoint fallback
    (demanding the vestad env) instead of failing on a missing repo path."""
    home = tmp_path / "home"
    home.mkdir()
    env = _env(home, {"AGENT_NAME": "testbox"})
    env.pop("VESTAD_PORT", None)
    r = subprocess.run(["bash", str(FETCH)], cwd=str(home), env=env, capture_output=True, text=True, check=False)
    assert r.returncode != 0
    assert "VESTAD_PORT" in r.stderr
