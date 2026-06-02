"""Exercises the REAL upstream-sync shell scripts against real git repos.

These tests run the actual scripts (`narrow-sparse-checkout.sh`, `skills-install`,
`reanchor.sh`) rather than reimplementing their commands, so the scripts themselves
are under test and can't silently drift from their behaviour. No Docker, no network:
a local repo on disk stands in for "upstream".

The scenarios pin the assumptions that the upstream-sync flow relies on and that
broke in production: sparse-cone scoping, idempotency, skills-install error/revert
paths, and the no-common-ancestor re-anchor (including a committed-core divergence,
which is the exact failure that put `agent/core/` onto an agent's branch).
"""

import json
import os
import shutil
import subprocess
import pathlib as pl

import pytest

AGENT_ROOT = pl.Path(__file__).resolve().parents[1]
NARROW = AGENT_ROOT / "skills/upstream-sync/scripts/narrow-sparse-checkout.sh"
SYNC = AGENT_ROOT / "skills/upstream-sync/scripts/sync.sh"
STATUS = AGENT_ROOT / "skills/upstream-sync/scripts/status.sh"
SKILLS_INSTALL = AGENT_ROOT / "skills/skills-registry/scripts/skills-install"


def _registry(names):
    return json.dumps([{"name": n} for n in sorted(names)], indent=2) + "\n"


NARROW_HEADER = ["/agent/", "!/agent/core/", "!/agent/pyproject.toml", "!/agent/uv.lock", "!/agent/skills/*/", "/.gitignore"]

BASE_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}

# These drive real git repos on disk (local clones share object storage via
# alternates), so they must not be parallelised against each other if xdist is
# ever added. CI runs pytest serially today.
pytestmark = pytest.mark.skipif(shutil.which("git") is None or shutil.which("tar") is None, reason="git and tar required")


def _env(home, extra=None):
    e = os.environ.copy()
    e.pop("VESTA_UPSTREAM_REF", None)
    e.update(BASE_ENV)
    e["HOME"] = str(home)
    if extra:
        e.update(extra)
    return e


def _git(args, cwd, extra_env=None):
    r = subprocess.run(["git", *args], cwd=str(cwd), env=_env(cwd, extra_env), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}"
    return r.stdout


def _merge_base(home):
    return subprocess.run(["git", "merge-base", "HEAD", "FETCH_HEAD"], cwd=str(home), env=_env(home), capture_output=True, text=True)


def _run(script, home, args=(), extra_env=None):
    return subprocess.run(["bash", str(script), *args], cwd=str(home), env=_env(home, extra_env), capture_output=True, text=True)


def _sparse(home):
    return (home / ".git" / "info" / "sparse-checkout").read_text()


def _write_sparse(home, lines):
    (home / ".git" / "info").mkdir(parents=True, exist_ok=True)
    (home / ".git" / "info" / "sparse-checkout").write_text("\n".join(lines) + "\n")


def make_upstream(path, skills):
    """A stand-in upstream repo on branch `main`."""
    path.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], path)
    (path / "agent" / "core").mkdir(parents=True)
    (path / "agent" / "core" / "x.py").write_text("UPSTREAM CORE\n")
    (path / "agent" / "MEMORY.md").write_text("# upstream template\n")
    (path / "agent" / "settings.txt").write_text("UPSTREAM SETTINGS\n")
    (path / ".gitignore").write_text("*.log\n")
    sk = path / "agent" / "skills"
    sk.mkdir(parents=True)
    for name in skills:
        (sk / name).mkdir()
        (sk / name / "SKILL.md").write_text(f"# upstream {name}\n")
    (sk / "index.json").write_text(_registry(skills))
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "upstream"], path)
    return "main"


def _upstream_skill_names(path):
    sk = path / "agent" / "skills"
    return [p.name for p in sk.iterdir() if p.is_dir() and (p / "SKILL.md").exists()]


def add_upstream_skill(path, name, body):
    (path / "agent" / "skills" / name).mkdir(parents=True)
    (path / "agent" / "skills" / name / "SKILL.md").write_text(body)
    (path / "agent" / "skills" / "index.json").write_text(_registry(_upstream_skill_names(path)))
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", f"add {name}"], path)


def add_upstream_file(path, rel, content, msg):
    p = path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", msg], path)


def make_synced_agent(home, upstream, *, cone_includes, broad=False):
    """Agent created by cloning upstream: shares history (steady-state)."""
    _git(["clone", "-q", "-b", "main", str(upstream), str(home)], home.parent)
    _git(["checkout", "-q", "-b", "agent"], home)
    _git(["sparse-checkout", "init", "--no-cone"], home)
    if broad:
        _write_sparse(home, ["/agent/", "/.gitignore"])
    else:
        _write_sparse(home, NARROW_HEADER + [f"/agent/skills/{n}/" for n in cone_includes])
    _git(["sparse-checkout", "reapply"], home)


def make_synthetic_agent(home, upstream, *, installed, self_authored=(), memory, core_content=None):
    """Agent created by `git init` with its own commits: NO shared history with upstream."""
    home.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "agent"], home)
    (home / "agent").mkdir(parents=True, exist_ok=True)
    (home / "agent" / "MEMORY.md").write_text(memory)
    (home / ".gitignore").write_text("local-ignore\n")
    sk = home / "agent" / "skills"
    sk.mkdir(parents=True)
    for name in list(installed) + list(self_authored):
        (sk / name).mkdir(parents=True, exist_ok=True)
        (sk / name / "SKILL.md").write_text(f"# LOCAL {name}\n")
    (sk / "index.json").write_text(_registry(list(installed) + list(self_authored)))
    if core_content is not None:
        (home / "agent" / "core").mkdir(parents=True, exist_ok=True)
        (home / "agent" / "core" / "x.py").write_text(core_content)
    _git(["add", "-A"], home)
    _git(["commit", "-q", "-m", "agent baseline"], home)
    _git(["sparse-checkout", "init", "--no-cone"], home)
    _write_sparse(home, NARROW_HEADER + [f"/agent/skills/{n}/" for n in list(installed) + list(self_authored)])
    _git(["sparse-checkout", "reapply"], home)
    _git(["remote", "add", "origin", str(upstream)], home)


# A committed agent/.gitignore the image ships and upstream also tracks. sync must NOT edit it
# (else the one-sided edit conflicts on every no-shared-history first sync); managed-mount
# ignores go to the repo-local .git/info/exclude instead.
AGENT_GITIGNORE = "# agent ignores\n*.log\nnode_modules/\n"


def make_first_start_agent(home, upstream, *, installed, memory):
    """Real first start: `git init`, NO baseline commit, and the vestad-managed mounts
    (agent/core, pyproject.toml, uv.lock) baked onto disk untracked and outside the sparse
    cone. The first `git add` the repo ever sees is sync.sh's own checkpoint, so if sync
    stages before gitignoring those paths, `git add` exits 1 on the out-of-cone files."""
    home.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q", "-b", "agent"], home)
    (home / "agent").mkdir(parents=True, exist_ok=True)
    (home / "agent" / "MEMORY.md").write_text(memory)
    (home / "agent" / ".gitignore").write_text(AGENT_GITIGNORE)
    (home / ".gitignore").write_text("local-ignore\n")
    sk = home / "agent" / "skills"
    sk.mkdir(parents=True)
    for name in installed:
        (sk / name).mkdir(parents=True, exist_ok=True)
        (sk / name / "SKILL.md").write_text(f"# LOCAL {name}\n")
    (sk / "index.json").write_text(_registry(list(installed)))
    (home / "agent" / "core").mkdir(parents=True, exist_ok=True)
    (home / "agent" / "core" / "x.py").write_text("MOUNTED CORE\n")
    (home / "agent" / "pyproject.toml").write_text("[project]\nname = 'agent'\n")
    (home / "agent" / "uv.lock").write_text("lock\n")
    _git(["sparse-checkout", "init", "--no-cone"], home)
    _write_sparse(home, NARROW_HEADER + [f"/agent/skills/{n}/" for n in installed])
    _git(["sparse-checkout", "reapply"], home)
    _git(["remote", "add", "origin", str(upstream)], home)


def place_skills_install(home):
    dst = home / "agent" / "skills" / "skills-registry" / "scripts" / "skills-install"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(SKILLS_INSTALL, dst)
    dst.chmod(0o755)
    return dst


# --- narrow-sparse-checkout.sh ------------------------------------------------


def test_narrow_is_idempotent(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"], broad=True)

    first = _run(NARROW, home)
    assert first.returncode == 0, first.stderr
    assert "!/agent/skills/*/" in _sparse(home)
    assert "/agent/skills/alpha/" in _sparse(home)
    assert "pre-op snapshot" in _git(["log", "--oneline"], home)

    second = _run(NARROW, home)
    assert second.returncode == 0
    assert "already narrow" in second.stdout


def test_narrowed_cone_keeps_new_upstream_skill_off_disk(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"], broad=True)

    assert _run(NARROW, home).returncode == 0

    add_upstream_skill(up, "newone", "# newone\n")
    _git(["fetch", "origin", "main"], home)
    _git(["merge", "FETCH_HEAD", "--no-edit"], home)

    assert not (home / "agent" / "skills" / "newone").exists()
    assert "agent/skills/newone/SKILL.md" in _git(["ls-files"], home)
    assert (home / "agent" / "skills" / "alpha").exists()


def test_narrow_errors_when_sparse_not_initialised(tmp_path):
    home = tmp_path / "agent"
    home.mkdir()
    _git(["init", "-q", "-b", "agent"], home)
    (home / "agent").mkdir()
    (home / "agent" / "x").write_text("x\n")
    _git(["add", "-A"], home)
    _git(["commit", "-q", "-m", "x"], home)

    r = _run(NARROW, home)
    assert r.returncode == 1
    assert "not initialised" in r.stderr


# --- skills-install -----------------------------------------------------------


def _install_agent(tmp_path, upstream_skills=("alpha",)):
    up = tmp_path / "up"
    make_upstream(up, list(upstream_skills))
    home = tmp_path / "agent"
    _git(["clone", "-q", "-b", "main", str(up), str(home)], home.parent)
    _git(["checkout", "-q", "-b", "agent"], home)
    place_skills_install(home)
    _git(["add", "-A"], home)
    _git(["commit", "-q", "-m", "scripts"], home)
    _git(["sparse-checkout", "init", "--no-cone"], home)
    _write_sparse(home, NARROW_HEADER + ["/agent/skills/alpha/", "/agent/skills/skills-registry/"])
    _git(["sparse-checkout", "reapply"], home)
    return up, home, home / "agent" / "skills" / "skills-registry" / "scripts" / "skills-install"


def test_skills_install_already_installed_is_noop(tmp_path):
    _up, home, script = _install_agent(tmp_path)
    r = _run(script, home, args=["alpha"], extra_env={"VESTA_UPSTREAM_REF": "main"})
    assert r.returncode == 0
    assert "already installed" in r.stdout


def test_skills_install_pulls_skill_from_upstream(tmp_path):
    up, home, script = _install_agent(tmp_path)
    add_upstream_skill(up, "extra", "# extra\n")

    assert not (home / "agent" / "skills" / "extra").exists()
    r = _run(script, home, args=["extra"], extra_env={"VESTA_UPSTREAM_REF": "main"})
    assert r.returncode == 0, r.stderr
    assert (home / "agent" / "skills" / "extra" / "SKILL.md").read_text() == "# extra\n"
    assert "/agent/skills/extra/" in _sparse(home)


def test_skills_install_unknown_skill_errors_and_reverts(tmp_path):
    _up, home, script = _install_agent(tmp_path)
    r = _run(script, home, args=["bogus"], extra_env={"VESTA_UPSTREAM_REF": "main"})
    assert r.returncode == 1
    assert "not found" in r.stderr
    assert "/agent/skills/bogus/" not in _sparse(home)
    assert not (home / "agent" / "skills" / "bogus").exists()


def test_skills_install_without_upstream_ref_errors_and_reverts(tmp_path):
    up, home, script = _install_agent(tmp_path)
    add_upstream_skill(up, "extra", "# extra\n")
    r = _run(script, home, args=["extra"])  # no VESTA_UPSTREAM_REF
    assert r.returncode == 1
    assert "VESTA_UPSTREAM_REF" in r.stderr
    assert "/agent/skills/extra/" not in _sparse(home)


# --- sync.sh ------------------------------------------------------------------

MAIN = {"VESTA_UPSTREAM_REF": "main"}


def test_sync_up_to_date(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"])

    r = _run(SYNC, home, extra_env=MAIN)
    assert r.returncode == 0, r.stderr
    assert "up to date" in r.stdout.lower()


def test_sync_clean_merge_pulls_content(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"])
    add_upstream_file(up, "agent/settings.txt", "UPSTREAM SETTINGS v2\n", "bump settings")

    r = _run(SYNC, home, extra_env=MAIN)
    assert r.returncode == 0, r.stderr
    assert (home / "agent" / "settings.txt").read_text() == "UPSTREAM SETTINGS v2\n"


def test_sync_keeps_index_json_as_full_registry(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha", "zeta"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"])  # only alpha on disk
    add_upstream_skill(up, "newreg", "# newreg\n")  # registry grows upstream

    r = _run(SYNC, home, extra_env=MAIN)
    assert r.returncode == 0, r.stderr

    names = {s["name"] for s in json.loads((home / "agent" / "skills" / "index.json").read_text())}
    assert names == {"alpha", "zeta", "newreg"}, "index.json must stay the full upstream registry"
    # ...but the uninstalled skills are not on disk (sparse worktree).
    assert not (home / "agent" / "skills" / "newreg").exists()
    assert not (home / "agent" / "skills" / "zeta").exists()


def test_sync_no_common_ancestor_surfaces_real_conflicts(tmp_path):
    """No shared history (recreated repo): sync merges with --allow-unrelated-histories
    and only genuinely different owned files conflict, no hardcoded preserve list."""
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synthetic_agent(home, up, installed=["alpha"], memory="# MY MEMORY\n")
    _git(["fetch", "origin", "main"], home)
    assert _merge_base(home).returncode != 0  # unrelated histories

    r = _run(SYNC, home, extra_env=MAIN)
    assert r.returncode == 2, r.stdout + r.stderr  # real conflicts surface
    assert "MEMORY.md" in r.stdout

    for rel in _git(["diff", "--name-only", "--diff-filter=U"], home).split():
        _git(["checkout", "--theirs", "--", rel], home)
        _git(["add", "--", rel], home)
    r2 = _run(SYNC, home, extra_env=MAIN)
    assert r2.returncode == 0, r2.stderr


def test_sync_first_start_with_managed_paths_on_disk(tmp_path):
    """Regression: on a fresh `git init` agent the vestad-managed mounts (agent/core,
    pyproject.toml, uv.lock) are on disk, untracked and outside the sparse cone. sync must
    gitignore them BEFORE its first `git add`, or `git add agent/` exits 1 on the out-of-cone
    files and (under set -e) the very first sync aborts. Owned files that differ from upstream
    must still surface as ordinary conflicts (exit 2), not a crash.

    sync must ignore the mounts via the repo-local .git/info/exclude, NOT by editing the
    committed agent/.gitignore: a one-sided edit to a file upstream also tracks conflicts on
    every no-shared-history first sync, so agent/.gitignore must merge cleanly."""
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    add_upstream_file(up, "agent/.gitignore", AGENT_GITIGNORE, "add agent gitignore")
    home = tmp_path / "agent"
    make_first_start_agent(home, up, installed=["alpha"], memory="# MY MEMORY\n")

    r = _run(SYNC, home, extra_env=MAIN)
    assert r.returncode == 2, r.stdout + r.stderr  # real conflicts, not an exit-1 crash
    assert "outside of your sparse-checkout" not in (r.stdout + r.stderr)
    assert "agent/.gitignore" not in r.stdout  # untouched file merges clean, no conflict
    assert (home / "agent" / "core" / "x.py").read_text() == "MOUNTED CORE\n"  # mount untouched
    assert "agent/core" not in _git(["ls-files"], home)  # never tracked
    assert "agent/core" not in _git(["status", "--short"], home)  # ignored, no noise
    assert (home / "agent" / ".gitignore").read_text() == AGENT_GITIGNORE  # committed file unchanged
    assert "agent/core" in (home / ".git" / "info" / "exclude").read_text()  # ignored locally instead


def test_sync_untracks_vestad_managed_core(tmp_path):
    """An agent that tracked agent/core has it dropped from tracking on sync, and stays
    gitignored (no noise)."""
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"])  # a clone, so core is tracked
    assert "agent/core/x.py" in _git(["ls-files"], home)
    add_upstream_file(up, "agent/core/x.py", "UPSTREAM CORE v2\n", "bump core")

    r = _run(SYNC, home, extra_env=MAIN)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "agent/core/x.py" not in _git(["ls-files"], home)  # no longer tracked
    assert "agent/core" not in _git(["status", "--short"], home)  # gitignored, no noise


def test_sync_quiet_against_read_only_core(tmp_path):
    """The real bind-mount case: agent/core is a read-only directory on disk. sync merges a
    core-less copy of upstream, so git never touches core, no read-only error even when
    upstream changed core."""
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"])
    core_dir = home / "agent" / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "x.py").write_text("MOUNTED CORE\n")
    add_upstream_file(up, "agent/core/x.py", "UPSTREAM CORE v2\n", "bump core")

    os.chmod(core_dir, 0o555)
    try:
        r = _run(SYNC, home, extra_env=MAIN)
    finally:
        os.chmod(core_dir, 0o755)

    assert r.returncode == 0, r.stdout + r.stderr
    blob = r.stdout + r.stderr
    assert "Read-only file system" not in blob
    assert "Permission denied" not in blob
    assert "unable to unlink" not in blob
    assert (core_dir / "x.py").read_text() == "MOUNTED CORE\n"  # untouched
    assert "agent/core/x.py" not in _git(["ls-files"], home)  # not tracked


def test_status_reports_behind_ahead_and_changes(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"])
    (home / "agent" / "MEMORY.md").write_text("# mine\n")
    _git(["add", "-A"], home)
    _git(["commit", "-q", "-m", "mine"], home)
    add_upstream_file(up, "agent/settings.txt", "v2\n", "up settings")

    r = _run(STATUS, home, extra_env=MAIN)
    assert r.returncode == 0, r.stderr
    assert "behind: 1" in r.stdout
    assert "ahead: 1" in r.stdout
    assert "incoming" in r.stdout.lower()
    assert "agent/MEMORY.md" in r.stdout  # your change
    assert "settings.txt" not in r.stdout.split("your changes")[-1]  # not mislabelled as yours


def test_status_reports_no_shared_history(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synthetic_agent(home, up, installed=["alpha"], memory="x\n")

    r = _run(STATUS, home, extra_env=MAIN)
    assert r.returncode == 0, r.stderr
    assert "no shared history" in r.stdout.lower()
