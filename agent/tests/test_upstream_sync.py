"""Exercises the REAL box workspace flow against local upstream repos (no network).

The box's ``~`` is a plain FULL git checkout of the agent-upstream snapshot (all skills +
MEMORY.md; the engine ``agent/core`` is a read-only mount, gitignored, never in the tree).
Which skills are ACTIVE is recorded in ``data/installed-skills.txt`` and materialized as the
``~/.claude/skills`` symlink farm by ``link-skills.sh``; every optional skill sits on disk
regardless. These tests build an upstream repo with the REAL build-upstream.sh (the script
vestad runs), then drive the REAL attach.sh / fetch-upstream.sh / sync.sh / link-skills.sh /
skills-install / skills-remove scripts in a fake ``$HOME``, pinning the flat-checkout
contract: clean attach, version-pinned rebase, offline activation, and the cone->flat
migration spine.
"""

import os
import pathlib as pl
import shutil
import subprocess
import sys

import pytest

AGENT_ROOT = pl.Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_ROOT.parent
BUILD = REPO_ROOT / "vestad/scripts/build-upstream.sh"
ATTACH = AGENT_ROOT / "core/skills/upstream-sync/scripts/attach.sh"
FETCH = AGENT_ROOT / "core/skills/upstream-sync/scripts/fetch-upstream.sh"
SYNC = AGENT_ROOT / "core/skills/upstream-sync/scripts/sync.sh"
STATUS = AGENT_ROOT / "core/skills/upstream-sync/scripts/status.sh"
LINK_SKILLS = AGENT_ROOT / "core/skills/upstream-sync/scripts/link-skills.sh"
SKILLS_INSTALL = AGENT_ROOT / "skills/skills-registry/scripts/skills-install"
SKILLS_REMOVE = AGENT_ROOT / "skills/skills-registry/scripts/skills-remove"
SKILLS_SEARCH = AGENT_ROOT / "skills/skills-registry/scripts/skills-search"
BRANCH = "agent-upstream"
# The optional skills every fixture snapshot ships on disk (a full checkout carries them all).
ALL_SKILLS = ("tasks", "dream", "whatsapp")
DEFAULT_SKILLS = ("tasks", "dream")
# LEGACY(remove-when: no agent predating the rename release remains): the forwarding shims
# old boxes' synced scripts and released migrations rely on (set-cone.sh is gone).
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
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


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
    for script in (ATTACH, FETCH, SYNC, STATUS, LINK_SKILLS):
        shutil.copy(script, scripts / script.name)
    forwarding = core_skills / "workspace-sync/scripts"
    forwarding.mkdir(parents=True, exist_ok=True)
    for shim in FORWARDING.glob("*.sh"):
        shutil.copy(shim, forwarding / shim.name)


def _box_gitignore():
    """The agent/.gitignore a flat-checkout image ships: the repo's, with the /core/ mount
    scope build-upstream.sh appends to the snapshot. It must already carry /core/ or every
    box's tree is dirty (the read-only core mount shows as untracked); this mirrors the
    snapshot so a fresh attach lands clean."""
    return (AGENT_ROOT / ".gitignore").read_text() + "/core/\n"


def _memory_template(version):
    # Realistic shape: a version-touched header far from the tail agents append to,
    # so a template bump and a local note merge cleanly (as they do in real MEMORY.md).
    return f"# memory template {version}\n\n## About\n\nstable section\n\n## Notes\n\n"


def _write_content(content, version):
    """A stand-in extracted agent-code dir, as ensure_agent_code leaves it: core (stripped from
    the snapshot by build-upstream.sh) + every skill + MEMORY.md."""
    (content / "core").mkdir(parents=True, exist_ok=True)
    (content / "core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (content / "core/loops.py").write_text(f"# core at {version}\n")
    for skill in ALL_SKILLS:
        d = content / "skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {skill} at {version}\n---\n")
    (content / "MEMORY.md").write_text(_memory_template(version))
    (content / ".gitignore").write_text((AGENT_ROOT / ".gitignore").read_text())
    (content / "ruff.toml").write_text("line-length = 144\n")  # box needs it (formatting); ships in the snapshot
    _copy_sync_scripts(content / "core/skills")


def _upstream_fixture(tmp_path, versions=("0.1.170",)):
    """Build an upstream repo with the REAL build-upstream.sh, one snapshot per version.
    Returns the bare repo path (what a box's fetch-upstream.sh consumes; on real boxes it
    is bind-mounted at /run/vesta-upstream/upstream.git)."""
    content = tmp_path / "agent-code"
    ws = tmp_path / "upstream"
    for version in versions:
        _write_content(content, version)
        r = subprocess.run(
            ["bash", str(BUILD), str(content), str(ws), version], env=_env(tmp_path), capture_output=True, text=True, check=False
        )
        assert r.returncode == 0, r.stdout + r.stderr
    return ws / "upstream.git"


def _write_core_mount(home, version="0.1.170"):
    """The read-only engine mount at agent/core: on disk under agent/ but gitignored (/core/),
    so it never enters the checkout. A real bind mount persists through any git operation; a
    plain dir is re-materialized after sparse-checkout would otherwise strip it."""
    core = home / "agent/core"
    core.mkdir(parents=True, exist_ok=True)
    (core / "pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (core / "loops.py").write_text(f"# core at {version}\n")
    (core / "default-skills.txt").write_text("\n".join(DEFAULT_SKILLS) + "\n")
    _copy_sync_scripts(core / "skills")


def _fresh_box(tmp_path, version="0.1.170", skills=ALL_SKILLS):
    """A fake $HOME as the image ships it: snapshot content on disk (every skill), no .git.

    Which skills are active lives in data/installed-skills.txt, not on disk (every skill is
    present regardless)."""
    home = tmp_path / "home"
    _write_core_mount(home, version)
    for skill in skills:
        d = home / "agent/skills" / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {skill} at {version}\n---\n")
    (home / "agent/MEMORY.md").write_text(_memory_template(version))
    (home / "agent/.gitignore").write_text(_box_gitignore())
    (home / "agent/constitution.md").write_text("# user rules\n")  # bind-mounted read-only on real boxes
    (home / "agent/ruff.toml").write_text("line-length = 144\n")  # shipped in the image; tracked, must stay clean
    return home


def _box_env(source):
    return {"VESTA_UPSTREAM_SOURCE": str(source), "AGENT_NAME": "testbox"}


def _attach(home, source):
    return _run(ATTACH, home, extra_env=_box_env(source))


def _installed(home):
    f = home / "agent/data/installed-skills.txt"
    return sorted(name for name in f.read_text().split() if name) if f.exists() else []


def _links(home):
    d = home / ".claude/skills"
    return sorted(p.name for p in d.iterdir()) if d.exists() else []


# --- attach: the flat full checkout ------------------------------------------------------


def test_fresh_attach_is_clean_and_ships_every_skill(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    marker = home / "agent/skills/tasks/SKILL.md"
    before = marker.read_text()
    r = _attach(home, source)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == before  # present files left as-is
    assert _git(["status", "--porcelain"], home, _box_env(source)) == ""  # clean: core gitignored, no ?? core/
    # Full checkout: every skill is on disk, active or not (whatsapp is not a default).
    for skill in ALL_SKILLS:
        assert (home / "agent/skills" / skill / "SKILL.md").exists()


def test_attach_is_idempotent(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    assert _attach(home, source).returncode == 0
    assert _attach(home, source).returncode == 0
    assert _git(["status", "--porcelain"], home, _box_env(source)) == ""


def test_attach_materializes_the_core_scoping_gitignore_out_of_tree(tmp_path):
    """agent/core exists on disk (the mount) but the snapshot gitignores it (/core/), so a
    fresh attach never reports it as untracked and add -A never stages it."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    (home / "agent/core/loops.py").write_text("# mount content, newer\n")  # mount drift is invisible
    assert "agent/core" not in _git(["status", "--porcelain"], home, env)
    _git(["add", "-A"], home, env)
    assert "agent/core" not in _git(["diff", "--cached", "--name-only"], home, env)


def test_attach_refuses_a_legacy_sparse_cone(tmp_path):
    """A sparse-cone workspace is the old shape; attach must refuse it (exit 4) so the
    flat-checkout boot migration owns the one-way conversion, never a half-convert."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    r = _attach(home, source)
    assert r.returncode == 4
    assert "legacy" in r.stderr


def test_attach_fails_loudly_when_snapshot_missing(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170",))
    home = _fresh_box(tmp_path, version="0.1.999")  # no agent-v0.1.999 in the upstream repo
    r = _attach(home, source)
    assert r.returncode == 3
    assert "agent-v0.1.999" in r.stderr


# --- sync: put HEAD on the running version's snapshot, local work rebased on top ---------


def test_sync_rebases_local_changes_onto_the_new_snapshot(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "my personal notes\n")  # uncommitted; sync.sh checkpoints it
    # The engine mount now runs 0.1.171; it is gitignored so this disk change is invisible to git.
    (home / "agent/core/pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "0.1.171"\n')
    r = _run(SYNC, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "my personal notes" in memory.read_text()  # my work survives
    assert "0.1.171" in (home / "agent/skills/tasks/SKILL.md").read_text()  # stock moved
    _git(["merge-base", "--is-ancestor", "agent-v0.1.171", "HEAD"], home, env)  # what the boot turn re-fires on


def test_sync_is_idempotent_once_synced(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    head = _git(["rev-parse", "HEAD"], home, env)
    r = _run(SYNC, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "already synced" in r.stdout
    assert _git(["rev-parse", "HEAD"], home, env) == head


def test_sync_conflict_stops_with_a_hint(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    (home / "agent/skills/tasks/SKILL.md").write_text("mine\n")  # conflicts with 0.1.171's edit
    (home / "agent/core/pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "0.1.171"\n')
    r = _run(SYNC, home, extra_env=env)
    assert r.returncode == 5
    assert "rebase stopped" in r.stderr


def test_status_reports_the_authoritative_sync_answer(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0  # attaches at 0.1.170
    (home / "agent/core/pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "0.1.171"\n')
    r = _run(STATUS, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT synced" in r.stdout  # HEAD is on 0.1.170, running core is 0.1.171
    assert _run(SYNC, home, extra_env=env).returncode == 0
    r = _run(STATUS, home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT synced" not in r.stdout and "synced" in r.stdout


def test_downgrade_transplants_delta_onto_older_snapshot(tmp_path):
    source = _upstream_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, version="0.1.171")
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "keep me\n")
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    _git(["rebase", "--onto", "agent-v0.1.170", "agent-v0.1.171"], home, env)
    assert "keep me" in memory.read_text()
    assert "0.1.170" in (home / "agent/skills/tasks/SKILL.md").read_text()


# --- skills: installed-skills.txt + the ~/.claude/skills symlink farm --------------------


def test_install_activates_offline_without_touching_git(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    shutil.rmtree(source)  # sever the source: activation is local, no fetch
    r = _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Restart Vesta to activate it" in r.stdout
    assert "whatsapp" in _installed(home)  # recorded active
    assert (home / ".claude/skills/whatsapp").is_symlink()  # linked into the farm
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()  # was always on disk
    assert _git(["status", "--porcelain"], home, env) == ""  # activation is not a git change


def test_install_unknown_skill_errors(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    r = _run(SKILLS_INSTALL, home, args=("nope",), extra_env=env)
    assert r.returncode == 1
    assert "no skill 'nope'" in r.stderr
    assert "nope" not in _installed(home)


def test_remove_deactivates_but_keeps_the_files_on_disk(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    assert _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=env).returncode == 0
    r = _run(SKILLS_REMOVE, home, args=("whatsapp",), extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Restart Vesta to deactivate it" in r.stdout
    assert "whatsapp" not in _installed(home)  # dropped from the active list
    assert not (home / ".claude/skills/whatsapp").exists()  # symlink gone
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()  # files stay (full checkout)


def test_remove_not_installed_is_reported(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    r = _run(SKILLS_REMOVE, home, args=("whatsapp",), extra_env=env)
    assert r.returncode == 0
    assert "is not installed" in r.stdout


def test_search_lists_local_catalog_and_marks_installed(tmp_path):
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    assert _attach(home, source).returncode == 0
    assert _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=env).returncode == 0
    r = subprocess.run([sys.executable, str(SKILLS_SEARCH)], cwd=str(home), env=_env(home, env), capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = {line.split(":")[0]: line for line in r.stdout.splitlines()}
    assert set(ALL_SKILLS) <= lines.keys()  # every on-disk skill is in the catalog
    assert "[installed]" in lines["whatsapp"]  # activation is marked from installed-skills.txt


# --- link-skills.sh: the one gate turning the installed list into the symlink farm -------


def _link_skills_box(tmp_path, defaults=DEFAULT_SKILLS, optional=("tasks", "dream", "whatsapp", "microsoft")):
    home = tmp_path / "home"
    (home / "agent/core/skills").mkdir(parents=True)
    for core_skill in ("app-chat", "upstream-sync"):
        d = home / "agent/core/skills" / core_skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {core_skill}\ndescription: core\n---\n")
    shutil.copy(LINK_SKILLS, home / "agent/core/skills/upstream-sync/link-skills.sh")
    for skill in optional:
        d = home / "agent/skills" / skill
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: opt\n---\n")
    (home / "agent/core/default-skills.txt").write_text("\n".join(defaults) + "\n")
    return home, home / "agent/core/skills/upstream-sync/link-skills.sh"


def test_link_skills_seeds_defaults_and_always_links_core(tmp_path):
    home, script = _link_skills_box(tmp_path)
    assert _run(script, home).returncode == 0
    assert _installed(home) == sorted(DEFAULT_SKILLS)  # seeded from the shipped defaults
    # Defaults + every core skill are linked; an uninstalled optional (whatsapp) is not.
    assert set(_links(home)) == {*DEFAULT_SKILLS, "app-chat", "upstream-sync"}
    assert "whatsapp" not in _links(home)


def test_link_skills_unions_a_newly_shipped_default(tmp_path):
    home, script = _link_skills_box(tmp_path)
    assert _run(script, home).returncode == 0
    (home / "agent/core/default-skills.txt").write_text("\n".join((*DEFAULT_SKILLS, "whatsapp")) + "\n")  # an upgrade's new default
    assert _run(script, home).returncode == 0
    assert "whatsapp" in _installed(home) and "whatsapp" in _links(home)


def test_link_skills_drops_a_deactivated_optional(tmp_path):
    home, script = _link_skills_box(tmp_path)
    assert _run(script, home).returncode == 0
    installed = home / "agent/data/installed-skills.txt"
    installed.write_text(installed.read_text() + "microsoft\n")  # activate a non-default
    assert _run(script, home).returncode == 0
    assert "microsoft" in _links(home)
    installed.write_text("\n".join(DEFAULT_SKILLS) + "\n")  # deactivate it again
    assert _run(script, home).returncode == 0
    assert "microsoft" not in _links(home)  # removed leaves no dangling link
    assert set(DEFAULT_SKILLS) <= set(_links(home))  # defaults still linked


# --- the cone->flat boot migration spine (2026-08-flat-checkout.md) ----------------------


def _legacy_cone_box(tmp_path, source, installed=("tasks", "dream")):
    """A pre-flat box: a sparse cone-mode checkout with only some skills active (on disk),
    carrying a personalization in MEMORY.md."""
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    _git(["init", "-b", "testbox"], home, env)
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "init"], home, env)
    _git(["sparse-checkout", "init", "--cone"], home, env)
    _git(["sparse-checkout", "set", *(f"agent/skills/{name}" for name in installed)], home, env)
    _write_core_mount(home)  # the cone strips the untracked dir; a real bind mount always persists
    memory = home / "agent/MEMORY.md"
    memory.write_text(memory.read_text() + "my personal notes\n")
    return home, env


def test_flat_checkout_migration_converts_cone_to_flat(tmp_path):
    """The 2026-08-flat-checkout spine: probe (attach refuses the cone, exit 4), capture the
    installed skills, retire the old repo, attach the flat one, reconcile personalizations."""
    source = _upstream_fixture(tmp_path)
    home, env = _legacy_cone_box(tmp_path, source, installed=("tasks", "dream"))
    # An uninstalled skill is off disk in the cone; a full checkout will restore it.
    assert not (home / "agent/skills/whatsapp").exists()

    # 1. Probe: attach refuses to touch the cone.
    assert _attach(home, source).returncode == 4

    # 2. Convert: record the active skills, retire the cone, attach flat.
    (home / "agent/data").mkdir(parents=True, exist_ok=True)
    cone = _git(["sparse-checkout", "list"], home, env)
    active = sorted(line[len("agent/skills/") :] for line in cone.splitlines() if line.startswith("agent/skills/"))
    (home / "agent/data/installed-skills.txt").write_text("\n".join(active) + "\n")
    (home / ".git").rename(home / ".git-legacy")
    assert _attach(home, source).returncode == 0

    # 3. Flat, personalization preserved, every skill materialized.
    assert not (home / ".git/info/sparse-checkout").exists()  # no cone
    sparse = subprocess.run(
        ["git", "config", "--get", "core.sparseCheckout"], cwd=str(home), env=_env(home, env), capture_output=True, text=True, check=False
    )
    assert sparse.stdout.strip() != "true"  # unset (exit 1) or false: the flat repo is not sparse
    assert _installed(home) == ["dream", "tasks"]  # active set captured
    status = _git(["status", "--porcelain"], home, env)
    assert "agent/MEMORY.md" in status  # personalization surfaced, not lost
    assert "my personal notes" in (home / "agent/MEMORY.md").read_text()
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()  # restored by the full checkout


# --- LEGACY forwarding + bundle (pre-rename boxes) ---------------------------------------


def test_forwarding_workspace_sync_scripts_behave_identically(tmp_path):
    """LEGACY(remove-when: no agent predating the rename release remains): released
    migrations call the old script paths verbatim; the shims must forward."""
    source = _upstream_fixture(tmp_path)
    home = _fresh_box(tmp_path)
    env = _box_env(source)
    r = _run(home / "agent/core/skills/workspace-sync/scripts/attach.sh", home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(["status", "--porcelain"], home, env) == ""
    r = _run(home / "agent/core/skills/workspace-sync/scripts/fetch-workspace.sh", home, extra_env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _git(["rev-parse", "refs/remotes/upstream/agent-upstream"], home, env).strip()


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
