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

import os
import shutil
import subprocess
import pathlib as pl

import pytest

AGENT_ROOT = pl.Path(__file__).resolve().parents[1]
NARROW = AGENT_ROOT / "skills/upstream-sync/scripts/narrow-sparse-checkout.sh"
REANCHOR = AGENT_ROOT / "skills/upstream-sync/scripts/reanchor.sh"
SKILLS_INSTALL = AGENT_ROOT / "skills/skills-registry/scripts/skills-install"

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
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", "upstream"], path)
    return "main"


def add_upstream_skill(path, name, body):
    (path / "agent" / "skills" / name).mkdir(parents=True)
    (path / "agent" / "skills" / name / "SKILL.md").write_text(body)
    _git(["add", "-A"], path)
    _git(["commit", "-q", "-m", f"add {name}"], path)


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
    if core_content is not None:
        (home / "agent" / "core").mkdir(parents=True, exist_ok=True)
        (home / "agent" / "core" / "x.py").write_text(core_content)
    _git(["add", "-A"], home)
    _git(["commit", "-q", "-m", "agent baseline"], home)
    _git(["sparse-checkout", "init", "--no-cone"], home)
    _write_sparse(home, NARROW_HEADER + [f"/agent/skills/{n}/" for n in list(installed) + list(self_authored)])
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


# --- reanchor.sh --------------------------------------------------------------


def test_reanchor_errors_without_fetch_head(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synthetic_agent(home, up, installed=["alpha"], memory="x\n")

    r = _run(REANCHOR, home)
    assert r.returncode == 1
    assert "FETCH_HEAD" in r.stderr


def test_reanchor_noops_when_common_ancestor(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha"])
    home = tmp_path / "agent"
    make_synced_agent(home, up, cone_includes=["alpha"])
    _git(["fetch", "origin", "main"], home)
    head_before = _git(["rev-parse", "HEAD"], home).strip()

    r = _run(REANCHOR, home)
    assert r.returncode == 0
    assert "common ancestor" in r.stdout
    assert _git(["rev-parse", "HEAD"], home).strip() == head_before


def test_reanchor_no_common_ancestor_pulls_upstream_and_preserves_owned(tmp_path):
    up = tmp_path / "up"
    make_upstream(up, ["alpha", "zeta"])  # zeta is an upstream-only, not-installed skill
    home = tmp_path / "agent"
    make_synthetic_agent(
        home,
        up,
        installed=["alpha"],
        self_authored=["mine"],
        memory="# USER MEMORY\nemilio\n",
        core_content="LOCAL CORE\n",  # a committed core divergence (the production bug)
    )

    _git(["fetch", "origin", "main"], home)
    assert _merge_base(home).returncode != 0, "fixture must have no common ancestor"

    r = _run(REANCHOR, home)
    assert r.returncode == 0, r.stderr

    # Now anchored: upstream is an ancestor.
    assert _merge_base(home).returncode == 0

    # Owned files preserved verbatim.
    assert (home / "agent" / "MEMORY.md").read_text() == "# USER MEMORY\nemilio\n"
    assert (home / "agent" / "skills" / "alpha" / "SKILL.md").read_text() == "# LOCAL alpha\n"
    assert (home / "agent" / "skills" / "mine" / "SKILL.md").exists()  # self-authored kept
    assert (home / ".gitignore").read_text() == "local-ignore\n"

    # All upstream content is now tracked.
    tracked = _git(["ls-files"], home)
    assert "agent/skills/zeta/SKILL.md" in tracked
    assert "agent/core/x.py" in tracked
    assert "agent/settings.txt" in tracked

    # Uninstalled upstream skill stays off disk (cone), non-owned in-cone file is upstream's.
    assert not (home / "agent" / "skills" / "zeta").exists()
    assert _git(["show", "HEAD:agent/settings.txt"], home) == "UPSTREAM SETTINGS\n"

    # The committed core divergence is gone: HEAD core matches upstream, not "LOCAL CORE".
    assert _git(["show", "HEAD:agent/core/x.py"], home) == "UPSTREAM CORE\n"

    # No conflict markers anywhere.
    assert "<<<<<<<" not in (home / "agent" / "MEMORY.md").read_text()
