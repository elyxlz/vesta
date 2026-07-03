# Vestad-Local Workspace Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the github `agent-workspace` branch with a per-host workspace repo + bundle that vestad builds at startup from its embedded agent content and serves to its boxes over the loopback — same sync flow in dev, tests, and prod.

**Architecture:** vestad embeds the full agent home, and one tested bash script (`vestad/scripts/build-workspace.sh`, descendant of `tools/publish-agent-branch.sh`) appends a snapshot commit + `agent-vX.Y.Z` tag to a local bare repo and regenerates `workspace.bundle` whenever the shipped content changes. A thin Rust wrapper (`vestad/src/workspace.rs`) runs it after `ensure_agent_code`; a self-scoped endpoint serves the bundle. Box-side, `fetch-workspace.sh` (curl → `git fetch <bundle>`) replaces `git fetch origin`; attach/rebase/cone porcelain is otherwise unchanged.

**Tech Stack:** Rust (vestad, axum, `include_str!`), bash + git plumbing (`write-tree`/`commit-tree`/`bundle`), Python 3.12 pytest (real-git harness), curl over loopback TLS.

**Spec:** `docs/superpowers/specs/2026-07-03-vestad-local-workspace-distribution.md` — read it before starting any task.

**This is a pivot of a live branch.** `feat/agent-branch-distribution` (PR #965) already implements the engine move, the boot turn + `mark_workspace_synced`, the workspace-sync core skill, and the github distribution. Tasks below transform or delete the github pieces; the "already landed, must change" inventory is baked into the task list — do not skip the deletion steps, a cohesive PR is the point.

## Global Constraints

- Python: always `uv run`, never bare `python`. No `getattr`/dict-`.get()` fallback/`hasattr`. Line length 144 (ruff). Agent suite invokes via `uv run --project core` with `UV_PROJECT_ENVIRONMENT="$PWD/.venv"` exported (or just `./check.sh agent`).
- Rust: no `panic!`/`unwrap`/`expect` on fallible paths; named consts; descriptive names; errors implement `std::error::Error`, lowercase `Display`, no trailing punctuation.
- Copy/prose: the agent is "Vesta" or "they/them"; no em/en dashes in `SKILL.md`/migration/prompt files; agent-facing copy describes current behavior only (no change rationale).
- Conventional Commits, imperative, no trailing period. **No version bumps.**
- Branch name inside bundles: `agent-workspace` (constant). Tags: `agent-vX.Y.Z`. Bundle env override for tests: `VESTA_WORKSPACE_BUNDLE`.
- All work happens on `feat/agent-branch-distribution`; one commit per task. Tasks 2 and 3 run back-to-back (agent suite transiently red between them).
- Skills index: after any skill edit run `uv run python agent/skills/generate-index.py` (repo root) and commit `agent/skills/index.json`.
- Tests must not depend on network or a running vestad (except the Docker-gated integration suite).

---

### Task 1: Widen the vestad embed to the full agent home

**Files:**
- Modify: `vestad/src/agent_embed.rs`
- Modify: `vestad/build.rs` (embed-hash inputs, currently `collect_embed_inputs(&repo_root.join("agent/core"), ...)`)
- Modify: `vestad/src/agent_code.rs` (extraction test)

**Interfaces:**
- Produces: `ensure_agent_code(config)` extracts the complete publishable tree to `<config>/agent-code/`: `core/**`, `skills/**`, `MEMORY.md`, `.gitignore` (plus the existing `.vestad-fingerprint` marker). Task 2's script consumes that directory as `<content-dir>`.

- [ ] **Step 1: Widen the embed**

Replace the include lines in `vestad/src/agent_embed.rs` (the `skills/personality/presets/*.md` line is subsumed by `skills/**/*`):

```rust
use rust_embed::RustEmbed;

#[derive(RustEmbed)]
#[folder = "../agent"]
// The complete publishable agent home: what build-workspace.sh snapshots and what
// boxes sync from. Dev-tool configs (ruff.toml, pytest.ini, ty.toml) and tests/ live
// outside these globs and are never shipped.
#[include = "core/**/*"]
#[include = "skills/**/*"]
#[include = "MEMORY.md"]
#[include = ".gitignore"]
#[exclude = "**/__pycache__/*"]
#[exclude = "**/*.pyc"]
#[exclude = "**/.venv/**"]
#[exclude = "**/node_modules/**"]
pub(crate) struct AgentSource;
```

- [ ] **Step 2: Widen the build.rs hash inputs to match**

In `vestad/build.rs`, replace:
```rust
    collect_embed_inputs(&repo_root.join("agent/core"), &mut embed_files);
```
with:
```rust
    for rel in ["agent/core", "agent/skills", "agent/MEMORY.md", "agent/.gitignore"] {
        collect_embed_inputs(&repo_root.join(rel), &mut embed_files);
    }
```
(Also extend `collect_embed_inputs`'s skip list with `.venv` and `node_modules` dir names, mirroring the embed excludes, so local dev junk can't perturb the hash: in its `for entry` loop change the `__pycache__` check to `if name == "__pycache__" || name == ".venv" || name == "node_modules" { continue; }`.)

- [ ] **Step 3: Extend the extraction test**

In `vestad/src/agent_code.rs`'s `ensure_extracts_expected_files_and_is_idempotent`, after the existing `core/prompts/...` assertions add:

```rust
        // The full home ships now: skills, the MEMORY template, and the agent .gitignore
        // all feed build-workspace.sh.
        assert!(dir.join("skills/skills-registry/SKILL.md").is_file());
        assert!(dir.join("MEMORY.md").is_file());
        assert!(dir.join(".gitignore").is_file());
```

- [ ] **Step 4: Run the vestad suite**

Run: `./check.sh vestad`
Expected: PASS. If the `.gitignore` assertion fails, rust-embed skipped the dotfile — fix by keeping the `#[include = ".gitignore"]` line and checking rust-embed's `include` matching (it matches paths, dotfiles included; if genuinely broken, embed it as `agent-gitignore` is NOT acceptable — investigate, the file must land at `.gitignore`).

- [ ] **Step 5: Commit**

```bash
git add vestad/src/agent_embed.rs vestad/build.rs vestad/src/agent_code.rs
git commit -m "feat(vestad): embed the full agent home, not just core"
```

---

### Task 2: build-workspace.sh + its test suite (transforms the publish script)

**Files:**
- Create: `vestad/scripts/build-workspace.sh` (mechanics descended from `tools/publish-agent-branch.sh`)
- Delete: `tools/publish-agent-branch.sh`
- Create: `agent/tests/test_build_workspace.py`
- Delete: `agent/tests/test_publish_agent_branch.py`

**Interfaces:**
- Produces: `build-workspace.sh <content-dir> <workspace-dir> <version>` — maintains `<workspace-dir>/workspace.git` (bare; branch `agent-workspace`, one snapshot commit per content change, tag `agent-v<version>` force-set to the head) and atomically regenerates `<workspace-dir>/workspace.bundle` (branch + `agent-v*` tags). Exit 0 on append and on no-op. The staged tree is `agent/<content>` plus a script-owned root `.gitignore`; the content-dir's `.vestad-fingerprint` is excluded.
- Consumed by: Task 3 (test fixtures build bundles with it), Task 4 (vestad embeds + executes it).
- Note: `agent/tests/test_workspace_sync.py` still references the deleted publish script after this task — the agent suite is transiently red; run Task 3 immediately after.

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_build_workspace.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project core pytest tests/test_build_workspace.py -v`
Expected: FAIL — script not found.

- [ ] **Step 3: Implement `vestad/scripts/build-workspace.sh`**

```bash
#!/usr/bin/env bash
# Maintain this host's agent-workspace repo and bundle from the extracted agent content.
# Run by vestad at startup (after ensure_agent_code); also tested directly by
# agent/tests/test_build_workspace.py -- the same file in both places, so tests and
# production cannot drift.
#
# Usage: build-workspace.sh <content-dir> <workspace-dir> <version>
#   content-dir    the extracted agent home (core/, skills/, MEMORY.md, .gitignore)
#   workspace-dir  owns workspace.git (bare) and workspace.bundle
#   version        the running vesta version; tags the snapshot agent-v<version>
#
# Append-only per host: one snapshot commit per content change on branch agent-workspace,
# tag agent-v<version> force-set to the head (it only actually moves under dev churn --
# releases bump the version every time). The bundle, not the repo, is what boxes fetch.
set -euo pipefail

CONTENT="${1:?Usage: build-workspace.sh <content-dir> <workspace-dir> <version>}"
WS="${2:?workspace-dir required}"
VERSION="${3:?version required}"
BRANCH="agent-workspace"
TAG="agent-v$VERSION"
REPO="$WS/workspace.git"
BUNDLE="$WS/workspace.bundle"

mkdir -p "$WS"
[ -d "$REPO" ] || git init -q --bare -b "$BRANCH" "$REPO"

STAGE="$(mktemp -d)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

# Staged tree: agent/<content> (sans the extraction fingerprint) + the root scoping
# .gitignore (everything in $HOME but agent/ stays out of git status on a box).
mkdir -p "$STAGE/agent"
cp -a "$CONTENT/." "$STAGE/agent/"
rm -f "$STAGE/agent/.vestad-fingerprint"
cat > "$STAGE/.gitignore" <<'EOF'
/*
!/.gitignore
!/agent/
EOF

export GIT_DIR="$REPO" GIT_WORK_TREE="$STAGE" GIT_INDEX_FILE="$STAGE/.build-index"
export GIT_AUTHOR_NAME="vesta" GIT_AUTHOR_EMAIL="vesta@vesta"
export GIT_COMMITTER_NAME="vesta" GIT_COMMITTER_EMAIL="vesta@vesta"

git add -A
TREE="$(git write-tree)"
PARENT="$(git rev-parse -q --verify "refs/heads/$BRANCH" || true)"

if [ -n "$PARENT" ] && [ "$(git rev-parse "$PARENT^{tree}")" = "$TREE" ] \
   && [ "$(git rev-parse -q --verify "refs/tags/$TAG^{commit}" || true)" = "$PARENT" ] \
   && [ -f "$BUNDLE" ]; then
  echo "workspace: no content change for v$VERSION; nothing to do"
  exit 0
fi

if [ -z "$PARENT" ] || [ "$(git rev-parse "$PARENT^{tree}")" != "$TREE" ]; then
  COMMIT="$(git commit-tree "$TREE" ${PARENT:+-p "$PARENT"} -m "snapshot v$VERSION")"
  git update-ref "refs/heads/$BRANCH" "$COMMIT"
fi
git tag -f "$TAG" "refs/heads/$BRANCH" >/dev/null

# Regenerate atomically: boxes may be mid-download of the old bundle; rename is safe.
git bundle create "$BUNDLE.tmp" "refs/heads/$BRANCH" --tags="agent-v*" 2>/dev/null \
  || git bundle create "$BUNDLE.tmp" "refs/heads/$BRANCH" $(git tag -l 'agent-v*' | sed 's|^|refs/tags/|')
mv "$BUNDLE.tmp" "$BUNDLE"
echo "workspace: $BRANCH at $TAG ($(git rev-parse --short "refs/heads/$BRANCH"))"
```

```bash
chmod +x vestad/scripts/build-workspace.sh
git rm -q tools/publish-agent-branch.sh agent/tests/test_publish_agent_branch.py
```

- [ ] **Step 4: Run tests, iterate**

Run: `cd agent && UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project core pytest tests/test_build_workspace.py -v`
Expected: PASS. Likely rough edges: `--tags=` glob support varies by git version (the fallback branch in the script handles it — verify one of the two paths actually runs); `git init -b` on old git. Fix the script, keep the tests as the contract.

- [ ] **Step 5: Commit**

```bash
git add vestad/scripts/build-workspace.sh agent/tests/test_build_workspace.py
git add -u tools/ agent/tests/
git commit -m "feat(vestad): build-workspace script maintains the per-host workspace repo and bundle"
```

---

### Task 3: Box scripts fetch from the bundle; box-flow tests re-fixture

**Files:**
- Create: `agent/core/skills/workspace-sync/scripts/fetch-workspace.sh`
- Rewrite: `agent/core/skills/workspace-sync/scripts/attach.sh` (drop remote config + `VESTA_WORKSPACE_REF`/`VESTA_UPSTREAM_URL`; fetch via the helper)
- Modify: `agent/core/skills/workspace-sync/scripts/status.sh` (same fetch swap)
- Modify: `agent/core/skills/workspace-sync/SKILL.md` (copy: no branch-name env; fetch step)
- Modify: `agent/core/migrations/2026-07-agent-branch-workspace.md` ("on the remote" → "from vestad")
- Rewrite fixtures in: `agent/tests/test_workspace_sync.py` (bundle-based; all behavioral tests keep their assertions)
- Regenerate: `agent/skills/index.json` (description unchanged → expected no-op; run anyway)

**Interfaces:**
- Consumes: `vestad/scripts/build-workspace.sh` (Task 2) for fixtures.
- Produces: `fetch-workspace.sh` — no args; if `VESTA_WORKSPACE_BUNDLE` is set fetches from that path (tests), else curls `https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/workspace.bundle` with `X-Agent-Token: $AGENT_TOKEN` to a temp file and fetches from it. Refspecs: `+refs/heads/agent-workspace:refs/remotes/origin/agent-workspace` and `+refs/tags/agent-v*:refs/tags/agent-v*`, `--no-tags`. `attach.sh` exit codes unchanged (0/3/4).

- [ ] **Step 1: fetch-workspace.sh**

```bash
#!/usr/bin/env bash
# Bring this box's workspace refs up to date from vestad's bundle. The "remote" is
# whatever bundle this box's vestad serves -- no configured URL, no external network.
# VESTA_WORKSPACE_BUNDLE overrides with a local bundle path (tests).
set -euo pipefail
cd ~

BUNDLE="${VESTA_WORKSPACE_BUNDLE:-}"
TMP=""
if [ -z "$BUNDLE" ]; then
  PORT="${VESTAD_PORT:?VESTAD_PORT is unset (source /run/vestad-env)}"
  NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
  TOKEN="${AGENT_TOKEN:?AGENT_TOKEN is unset (source /run/vestad-env)}"
  TMP="$(mktemp)"
  trap 'rm -f "$TMP"' EXIT
  # -k: vestad's cert is self-signed; loopback only (same trust model as vestad_client.py).
  curl -fsSk -H "X-Agent-Token: $TOKEN" "https://localhost:$PORT/agents/$NAME/workspace.bundle" -o "$TMP"
  BUNDLE="$TMP"
fi

git fetch --no-tags "$BUNDLE" \
  '+refs/heads/agent-workspace:refs/remotes/origin/agent-workspace' \
  '+refs/tags/agent-v*:refs/tags/agent-v*'
```

`chmod +x` it.

- [ ] **Step 2: Rewrite attach.sh**

Full new content (keeps: legacy detection, exit codes, cone, worktree-safe reset, root-.gitignore materialize, `sparse.expectFilesOutsideOfPatterns`; drops: `VESTA_WORKSPACE_REF`, `VESTA_UPSTREAM_URL`, all `git remote`/refspec/tagOpt config):

```bash
#!/usr/bin/env bash
# Attach $HOME to this vestad's workspace content. Idempotent and worktree-safe: the only
# working-tree-touching steps are `git reset --mixed` (never writes files) and materializing
# the root .gitignore when absent, so local content can never be clobbered - differences
# just show up in `git status` afterwards.
#
# Exit: 0 attached (or already attached); 3 snapshot tag for the running version not in
# the workspace bundle; 4 legacy workspace detected (the one-time workspace boot
# migration converts it: back up, retire ~/.git, re-run).
set -euo pipefail

NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
cd ~

VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"

if [ -d .git ]; then
  # Legacy shape: the pre-branch workspace used hand-built no-cone sparse patterns.
  # Cone-mode files also carry '!' lines, so key on the cone config: an attached
  # workspace always has core.sparseCheckoutCone=true, a legacy one never does.
  if [ -f .git/info/sparse-checkout ] && [ "$(git config --get core.sparseCheckoutCone || true)" != "true" ] && grep -q '^!' .git/info/sparse-checkout 2>/dev/null; then
    echo "legacy workspace detected: the one-time workspace boot migration converts it" >&2
    exit 4
  fi
else
  git init -b "$NAME"
fi

git config user.name "$NAME"
git config user.email "$NAME@vesta"
# The read-only core mount provides out-of-cone files on disk; without this, git
# clears their skip-worktree bit (present = "user wants it back") and mount content
# starts leaking into status and add -A.
git config sparse.expectFilesOutsideOfPatterns true

bash ~/agent/core/skills/workspace-sync/scripts/fetch-workspace.sh
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || {
  echo "snapshot $TAG not in the workspace bundle - is vestad on a different version?" >&2
  exit 3
}

# Cone = the skills on disk (installed set) - engine and uninstalled skills stay out.
find agent/skills -mindepth 1 -maxdepth 1 -type d | sort | git sparse-checkout set --cone --stdin

if ! git rev-parse -q --verify HEAD >/dev/null; then
  git update-ref "refs/heads/$NAME" "$TAG"
  git reset --mixed   # load index from the snapshot; worktree untouched
fi
# The branch's root .gitignore (ignore everything but agent/) keeps $HOME noise out of
# git status. The image doesn't ship it; materialize it when absent - creating a file
# that doesn't exist clobbers nothing.
[ -f .gitignore ] || git checkout -- .gitignore 2>/dev/null || true
echo "attached: branch $NAME on $TAG"
```

- [ ] **Step 3: status.sh fetch swap**

In `status.sh`: delete the `REF=...VESTA_WORKSPACE_REF...` line; replace `git fetch origin` with `bash ~/agent/core/skills/workspace-sync/scripts/fetch-workspace.sh`; replace both `"$REF"` mentions: the `echo "== snapshot $TAG not found on $REF"` line becomes `echo "== snapshot $TAG not in the workspace bundle"`, and the branch-tip line reads `git log --oneline -1 "refs/remotes/origin/agent-workspace" 2>/dev/null || echo "(not fetched)"`.

- [ ] **Step 4: SKILL.md copy**

In `agent/core/skills/workspace-sync/SKILL.md`:
- Intro sentence "Its `origin` carries the stock agent files for every Vesta version: one commit per release, tagged `agent-vX.Y.Z`, on the branch named by `$VESTA_WORKSPACE_REF`." becomes: "Vesta's daemon hands you the stock agent files for the version you run: one commit per release, tagged `agent-vX.Y.Z`, fetched as a bundle over the local machine (no internet involved)."
- In the Sync code block, replace `git fetch origin` with `bash ~/agent/core/skills/workspace-sync/scripts/fetch-workspace.sh`.
- In the unmanaged-core code block, replace `git fetch origin` the same way.

- [ ] **Step 5: Migration wording**

In `agent/core/migrations/2026-07-agent-branch-workspace.md`, replace both "not reachable on the remote right now" / "not on the remote" phrasings with "not available from vestad right now" (step 1's third bullet and step 2's failure paragraph).

- [ ] **Step 6: Re-fixture test_workspace_sync.py**

Changes (keep every test's assertions; only plumbing moves):
- Replace `PUBLISH = REPO_ROOT / "tools/publish-agent-branch.sh"` with `BUILD = REPO_ROOT / "vestad/scripts/build-workspace.sh"`.
- Replace `_publish_fixture` with a bundle fixture (no bare origin, no monorepo checkout):

```python
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
```

- `_write_content(content, version)` = the old `_write_monorepo_content` minus the `src / "agent/..."` prefix (files go at `content/core/...`, `content/skills/...`, `content/MEMORY.md`, `content/.gitignore`) and minus the git commit/publish steps; keep the same file bodies including `_memory_template` and the attach.sh copy under `content/skills/../` — **correction:** the attach.sh copy belongs under `content/core/skills/workspace-sync/scripts/` exactly as before, and also copy the new `fetch-workspace.sh` beside it (attach shells it at its ~-anchored path).
- `_box_env(bundle)` replaces `_box_env(origin)`:

```python
def _box_env(bundle):
    return {"VESTA_WORKSPACE_BUNDLE": str(bundle), "AGENT_NAME": "testbox"}
```

- `_fresh_box` also copies `fetch-workspace.sh` into the box's `agent/core/skills/workspace-sync/scripts/`.
- `_env` keeps `GIT_EDITOR` and drops the `e.pop("VESTA_WORKSPACE_REF", None)` line (pop `VESTA_WORKSPACE_BUNDLE` instead so a dev's env can't leak in).
- Every `origin, _ = _publish_fixture(...)` becomes `bundle = _bundle_fixture(...)`; every `_attach(home, origin)`/`_box_env(origin)` takes `bundle`.
- `test_install_is_offline_and_remove_drops_dir`: sever the source with `(tmp_path / "workspace" / "workspace.bundle").unlink()` instead of `shutil.rmtree(origin)` (install must not fetch).
- Module docstring: swap "published branch"/"origin" language for "workspace bundle".

- [ ] **Step 7: Run the suite**

Run: `cd agent && UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv run --project core pytest tests/test_workspace_sync.py tests/test_build_workspace.py -v`, then `./check.sh agent`
Expected: PASS (all 11 box-flow behaviors + build tests green).

- [ ] **Step 8: Regenerate index, commit**

```bash
uv run python agent/skills/generate-index.py
git add agent/core/skills/workspace-sync/ agent/core/migrations/ agent/tests/test_workspace_sync.py agent/skills/index.json
git commit -m "feat(skills): workspace-sync fetches from vestad's bundle over the loopback"
```

---

### Task 4: workspace.rs — thin wrapper running the script at startup

**Files:**
- Create: `vestad/src/workspace.rs`
- Modify: `vestad/src/main.rs` (module decl; find the `mod` list)
- Modify: `vestad/src/serve.rs` (~:2504, right after the `ensure_agent_code` call)

**Interfaces:**
- Consumes: `vestad/scripts/build-workspace.sh` (Task 2, via `include_str!`), `agent_code::ensure_agent_code` result (the content dir).
- Produces: `workspace::ensure_workspace(config_dir: &Path, content_dir: &Path) -> Result<(), WorkspaceError>`; `workspace::bundle_path(config_dir: &Path) -> PathBuf` (Task 5's handler reads it).

- [ ] **Step 1: Implement `vestad/src/workspace.rs`**

```rust
//! Thin edge around vestad/scripts/build-workspace.sh: the script owns all git logic
//! (and has its own real-git test suite in agent/tests/test_build_workspace.py); this
//! module only probes git, materializes the embedded script, and runs it.

use std::fmt;
use std::path::{Path, PathBuf};
use std::process::Command;

const BUILD_SCRIPT: &str = include_str!("../scripts/build-workspace.sh");
const SCRIPT_FILENAME: &str = "build-workspace.sh";

#[derive(Debug)]
pub enum WorkspaceError {
    GitMissing,
    Io(String),
    BuildFailed(String),
}

impl fmt::Display for WorkspaceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::GitMissing => write!(f, "git is required on the host to build the agent workspace (install git and restart vestad)"),
            Self::Io(msg) => write!(f, "workspace io error: {msg}"),
            Self::BuildFailed(msg) => write!(f, "build-workspace.sh failed: {msg}"),
        }
    }
}

impl std::error::Error for WorkspaceError {}

pub fn workspace_dir(config_dir: &Path) -> PathBuf {
    config_dir.join("workspace")
}

pub fn bundle_path(config_dir: &Path) -> PathBuf {
    workspace_dir(config_dir).join("workspace.bundle")
}

/// Build/refresh this host's workspace repo + bundle from the extracted agent content.
/// No-op (fast) when the content hasn't changed; the script owns that decision.
pub fn ensure_workspace(config_dir: &Path, content_dir: &Path) -> Result<(), WorkspaceError> {
    let git_ok = Command::new("git").arg("--version").output().map(|out| out.status.success());
    if !matches!(git_ok, Ok(true)) {
        return Err(WorkspaceError::GitMissing);
    }

    let dir = workspace_dir(config_dir);
    std::fs::create_dir_all(&dir).map_err(|e| WorkspaceError::Io(e.to_string()))?;
    let script = dir.join(SCRIPT_FILENAME);
    std::fs::write(&script, BUILD_SCRIPT).map_err(|e| WorkspaceError::Io(e.to_string()))?;

    let output = Command::new("bash")
        .arg(&script)
        .arg(content_dir)
        .arg(&dir)
        .arg(env!("CARGO_PKG_VERSION"))
        .output()
        .map_err(|e| WorkspaceError::Io(e.to_string()))?;
    if !output.status.success() {
        return Err(WorkspaceError::BuildFailed(String::from_utf8_lossy(&output.stderr).trim().to_string()));
    }
    tracing::info!("{}", String::from_utf8_lossy(&output.stdout).trim());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ensure_workspace_builds_bundle_from_content_dir() {
        let tmp = tempfile::tempdir().expect("tempdir");
        let content = tmp.path().join("agent-code");
        std::fs::create_dir_all(content.join("core")).expect("mkdir");
        std::fs::write(content.join("core/pyproject.toml"), "[project]\nname = \"vesta\"\nversion = \"0.0.0\"\n").expect("write");
        std::fs::write(content.join("MEMORY.md"), "# m\n").expect("write");

        ensure_workspace(tmp.path(), &content).expect("first build");
        assert!(bundle_path(tmp.path()).is_file());
        // Second run with unchanged content is a no-op, not an error.
        ensure_workspace(tmp.path(), &content).expect("no-op rerun");
    }
}
```

(The unit test invokes real git; it runs in `cargo test` like docker.rs's git-using tests. `CARGO_PKG_VERSION` tags `agent-v<crate version>` — fine for the test's assertions, which only check the bundle exists.)

- [ ] **Step 2: Register the module and hook startup**

`vestad/src/main.rs` (or wherever the `mod agent_code;` declaration lives — `rg -n 'mod agent_code' vestad/src`): add `mod workspace;` beside it (match `pub mod` if siblings use it).

`vestad/src/serve.rs` ~:2504 — extend the existing block:

```rust
    if let Err(e) = crate::agent_code::ensure_agent_code(&env_config.config_dir) {
```
so that on the success path it also builds the workspace. Match the surrounding error style; shape:

```rust
    match crate::agent_code::ensure_agent_code(&env_config.config_dir) {
        Err(e) => { /* keep the existing error handling exactly as-is */ }
        Ok(code_dir) => {
            if let Err(e) = crate::workspace::ensure_workspace(&env_config.config_dir, &code_dir) {
                // Boxes can't sync without the bundle, but vestad must still serve
                // (agents run fine between syncs). Loud, not fatal.
                tracing::error!(error = %e, "workspace build failed; agent workspace sync will be unavailable");
            }
        }
    }
```
(Read the existing code first; keep its `Err` arm byte-identical. If the current call discards the `Ok` value, bind it now — `ensure_agent_code` returns the content dir `PathBuf`.)

- [ ] **Step 3: Run the vestad suite**

Run: `./check.sh vestad`
Expected: PASS incl. the new workspace test.

- [ ] **Step 4: Commit**

```bash
git add vestad/src/workspace.rs vestad/src/main.rs vestad/src/serve.rs
git commit -m "feat(vestad): build the workspace repo and bundle at startup via the embedded script"
```

---

### Task 5: Serve the bundle — GET /agents/{name}/workspace.bundle

**Files:**
- Modify: `vestad/src/serve.rs` (handler + route in the agent-token router block ~:2210-2229; tests near the other handler tests)

**Interfaces:**
- Consumes: `workspace::bundle_path` (Task 4).
- Produces: `GET /agents/{name}/workspace.bundle`, agent-token authenticated and self-scoped (the existing `auth_middleware_agent_token` middleware already checks the token against `{name}`); 200 with the bundle bytes (`application/octet-stream`), 404 when no bundle exists yet.

- [ ] **Step 1: Handler**

Add near the other agent-scoped handlers in `serve.rs`:

```rust
/// `GET /agents/{name}/workspace.bundle` — the host's workspace bundle (branch + agent-v*
/// tags), fetched by the box's fetch-workspace.sh during attach/sync. Agent-token
/// authenticated; the middleware scopes the token to `{name}`, so a box can only pull
/// through its own identity (the content is host-global either way).
async fn workspace_bundle_handler(
    State(state): State<AppState>,
) -> Result<impl IntoResponse, (StatusCode, Json<serde_json::Value>)> {
    let path = crate::workspace::bundle_path(&state.env_config.config_dir);
    match tokio::fs::read(&path).await {
        Ok(bytes) => Ok(([(axum::http::header::CONTENT_TYPE, "application/octet-stream")], bytes)),
        Err(_) => Err((
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "workspace bundle not built yet"})),
        )),
    }
}
```

(Adjust imports/`AppState` field names to what neighboring handlers actually use — read `account_token_handler` first and mirror its signature style exactly.)

- [ ] **Step 2: Route**

In the agent-token router block (the one ending with `auth::auth_middleware_agent_token`), add:

```rust
        .route("/agents/{name}/workspace.bundle", get(workspace_bundle_handler))
```

- [ ] **Step 3: Tests**

Mirror how the existing serve.rs unit tests exercise handlers/auth (read the nearest `#[cfg(test)]` covering an agent-token route; if auth is only covered by integration tests, add the 404-vs-200 behavior test at the handler level):

```rust
    #[tokio::test]
    async fn workspace_bundle_handler_404s_before_first_build_and_serves_bytes_after() {
        // Build state with a tempdir config; call the handler; expect 404. Write a file at
        // workspace::bundle_path; call again; expect 200 and the same bytes.
    }
```
Fill in using the same state-construction helper the neighboring handler tests use (`rg -n 'fn test_state|AppState' vestad/src/serve.rs`). Assert both branches with concrete values (bytes round-trip).

- [ ] **Step 4: Run, commit**

Run: `./check.sh vestad` → PASS.

```bash
git add vestad/src/serve.rs
git commit -m "feat(vestad): serve the workspace bundle to agents over the loopback"
```

---

### Task 6: Retire VESTA_WORKSPACE_REF, detect_workspace_ref, and the pr.py env read

**Files:**
- Modify: `vestad/src/docker.rs` (env writer ~:976, env updater ~:1050-1085, `detect_workspace_ref` ~:887-905, its test ~:2318-2325)
- Modify: `agent/skills/upstream-pr/pr.py:90-93`
- Modify: `agent/skills/upstream-pr/SKILL.md` (three `$VESTA_WORKSPACE_REF` mentions)
- Regenerate: `agent/skills/index.json` (run; expected no-op)

**Interfaces:**
- Produces: no `VESTA_WORKSPACE_REF` anywhere except the LEGACY strip; env files converge on next vestad start.

- [ ] **Step 1: docker.rs**

- Delete `append_optional("VESTA_WORKSPACE_REF", detect_workspace_ref().as_deref());` from the env writer.
- Delete `pub fn detect_workspace_ref()` entirely, and its `detect_workspace_ref_dev_builds_use_per_branch_agent_branch` test.
- In `update_all_agent_env_files`: delete `let workspace_ref = detect_workspace_ref();` and the trailing `if let Some(workspace) = &workspace_ref { new_lines.push(...) }` block; keep the strip and update its comment:

```rust
                // LEGACY(remove-when: no agent env file carries VESTA_UPSTREAM_REF or
                // VESTA_WORKSPACE_REF): the workspace ref moved out of env entirely (boxes
                // fetch a bundle from vestad; no branch name needed) - strip stale keys.
                if stripped.starts_with("VESTAD_PORT=") || stripped.starts_with("VESTAD_TUNNEL=") || stripped.starts_with("VESTA_WORKSPACE_REF=") || stripped.starts_with("VESTA_UPSTREAM_REF=") {
```
- Update the updater's doc comment (drop the `VESTA_WORKSPACE_REF` mention: "Update VESTAD_PORT and VESTAD_TUNNEL in all existing per-agent env files ...").

- [ ] **Step 2: pr.py reads the version from the mounted core**

Replace lines 90-93 (`if "VESTA_WORKSPACE_REF" not in os.environ: ... upstream_ref = os.environ["VESTA_WORKSPACE_REF"]`) with:

```python
    pyproject = os.path.expanduser("~/agent/core/pyproject.toml")
    version_line = next((line for line in open(pyproject) if line.startswith("version = ")), "")
    vesta_version = version_line.split('"')[1] if '"' in version_line else "unknown"
```
and update the later uses of `upstream_ref` to `f"v{vesta_version}"` (grep `upstream_ref` in the file; it feeds PR-body attribution strings).

In `agent/skills/upstream-pr/SKILL.md`: "never from `$VESTA_WORKSPACE_REF` or local HEAD" → "never from the box's workspace or local HEAD"; "- Vesta version: `$VESTA_WORKSPACE_REF` (...)" → "- Vesta version: read from `~/agent/core/pyproject.toml`"; "Submitted by **$AGENT_NAME** on `$VESTA_WORKSPACE_REF`" → "Submitted by **$AGENT_NAME** on vesta v<version>".

- [ ] **Step 3: Sweep and verify**

```bash
git grep -n 'VESTA_WORKSPACE_REF\|VESTA_UPSTREAM_REF\|detect_workspace_ref\|VESTA_UPSTREAM_URL' -- ':!docs' ':!*.lock'
```
Expected: only docker.rs's LEGACY strip lines. Then `./check.sh vestad && ./check.sh agent` → PASS.

- [ ] **Step 4: Commit**

```bash
git add vestad/src/docker.rs agent/skills/upstream-pr/ agent/skills/index.json
git commit -m "refactor: retire VESTA_WORKSPACE_REF; boxes need no branch name"
```

---

### Task 7: Revert the CI publish job

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Remove the job and unwire needs**

- Delete the whole `publish-agent-branch:` job block (comment header included).
- `push-image:` needs back to `[test-linux, test-live]`.
- `release:` needs — remove `publish-agent-branch` from the list.
- `revert-failed-release:` needs — remove `publish-agent-branch` from the list.

- [ ] **Step 2: Validate and commit**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"` → `yaml ok`, and `git grep -c publish-agent-branch .github/` → no matches.

```bash
git add .github/workflows/ci.yml
git commit -m "build(ci): drop the agent-branch publish job (workspace ships with vestad)"
```

---

### Task 8: Docker-gated integration test — real container attaches through the endpoint

**Files:**
- Create: `vestad/tests/server/workspace.rs`
- Modify: `vestad/tests/server/main.rs` (or wherever sibling modules like `layout` are declared — `rg -n 'mod layout' vestad/tests`)

**Interfaces:**
- Consumes: the live endpoint (Task 5), `attach.sh`/`fetch-workspace.sh` shipped in the image's core.

- [ ] **Step 1: Write the test**

Mirror `layout.rs`'s harness (`TestAgent`, `exec_in_container`, `agent_container_name`, `mark_first_start_done`, `unique_agent`) — read it first and copy its setup shape:

```rust
use vesta_tests::{exec_in_container, agent_container_name, mark_first_start_done, unique_agent, TestAgent, SERVER};

/// The production sync path, end to end: the box curls its own vestad for the workspace
/// bundle and attaches. No synthetic remote anywhere.
#[test]
fn agent_attaches_to_the_workspace_through_the_bundle_endpoint() {
    let client = SERVER.client();
    let agent = TestAgent::create_with_manage_agent_code(&client, &unique_agent("ws-attach")).unwrap();
    mark_first_start_done(&agent.name).unwrap();
    client.restart_agent(&agent.name).unwrap();
    client.wait_until_running(&agent.name, 180).expect("agent up");
    let container = agent_container_name(&agent.name);

    let attach = exec_in_container(
        &container,
        ". /run/vestad-env && bash ~/agent/core/skills/workspace-sync/scripts/attach.sh",
    )
    .expect("attach succeeds");
    assert!(attach.contains("attached:"), "attach output: {attach}");

    let status = exec_in_container(&container, "cd ~ && git status --porcelain").expect("status");
    assert_eq!(status.trim(), "", "fresh attach must leave a clean tree, got: {status}");

    let tag = exec_in_container(&container, "cd ~ && git tag -l 'agent-v*'").expect("tags");
    assert!(!tag.trim().is_empty(), "an agent-v tag must be fetched from the bundle");
}
```

(Adjust helper names to what `layout.rs` really imports; if `exec_in_container` returns `Result<String,_>` with different semantics, follow it. The `create_with_manage_agent_code` + settle pattern comes from `agent_code.rs`'s tests.)

- [ ] **Step 2: Run the Docker suite**

Run: `./check.sh vestad-docker` (or the narrower `cd vestad && cargo test -p vesta-tests --test server workspace -- --ignored --nocapture` if the harness gates on `#[ignore]` — match how `layout.rs` tests are attributed).
Expected: PASS with Docker + the local image available.

- [ ] **Step 3: Commit**

```bash
git add vestad/tests/
git commit -m "test(vestad): live container attach through the workspace bundle endpoint"
```

---

### Task 9: Reference sweep — CLAUDE.md, spec status, PR body

**Files:**
- Modify: `CLAUDE.md` (the **Workspace sync** Key-Flows paragraph; the LLM-provider `.claude` invariant sentence)
- Modify: `.superpowers/sdd/progress.md` (append pivot tasks as they complete — bookkeeping only)

- [ ] **Step 1: CLAUDE.md Workspace sync paragraph**

Replace the whole `**Workspace sync (agent-branch distribution)**: ...` paragraph with:

> **Workspace sync (vestad-local distribution)**: vestad embeds the complete agent home (`agent/core`, `agent/skills`, `agent/MEMORY.md`, `agent/.gitignore`); at startup, after `ensure_agent_code`, `workspace.rs` runs the embedded `vestad/scripts/build-workspace.sh` (one tested bash script owning all git logic) to append a snapshot commit + `agent-vX.Y.Z` tag to the per-host bare repo at `~/.config/vesta/vestad/workspace/workspace.git` and regenerate `workspace.bundle`. Boxes fetch that bundle over the loopback (`GET /agents/{me}/workspace.bundle`, agent-token auth) via the workspace-sync core skill's `fetch-workspace.sh` — no github, no network, identical in dev/tests/prod. A box's `$HOME` is a cone-mode sparse checkout (`attach.sh`; the cone = installed skills). After a vestad upgrade the running core version (read from `core/pyproject.toml`) no longer matches the persisted `last_synced_version`, so `workspace_sync.py` queues a workspace-sync boot turn: the agent rebases its local changes onto `agent-v<version>` and records completion via the `mark_workspace_synced` tool (unmarked turns re-fire every boot). Managed boxes get the engine (= `agent/core/`) as one read-only mount, kept out of the checkout cone; unmanaged boxes (`--no-manage-core-code`) add `agent/core` to their cone and pull core through the same rebase.

- [ ] **Step 2: `.claude` invariant sentence**

In the LLM-provider paragraph, replace "The published agent branch never tracks `.claude` (the publish script's tree is an explicit allowlist), so converged workspaces cannot hit this;" with "The workspace snapshot never tracks `.claude` (build-workspace.sh stages an explicit allowlist), so converged workspaces cannot hit this;".

- [ ] **Step 3: Verify and commit**

```bash
git grep -n 'published agent branch\|publish-agent-branch\|agent-workspace branch' CLAUDE.md && echo "FIX THESE" || echo clean
git add CLAUDE.md
git commit -m "docs: describe vestad-local workspace distribution"
```

---

### Task 10: Final gate + PR update

- [ ] **Step 1: Full local gate**

```bash
./check.sh agent && ./check.sh vestad && ./check.sh cli
git grep -n 'publish-agent-branch\|VESTA_UPSTREAM_URL' -- ':!docs' && echo "STRAGGLERS" || echo clean
git grep -n 'VESTA_WORKSPACE_REF' -- ':!docs' ':!*.lock'   # expected: docker.rs LEGACY strip only
rg -n 'LEGACY\(' vestad/src agent/core agent/skills
```
Expected: suites green (`check.sh web` stays red from master — pre-existing, not this branch); grep results as annotated. LEGACY inventory: the entrypoint `.claude` guard, the dual-layout uv shim, the env-key strip, plus the pre-existing config/personality markers — nothing else.

- [ ] **Step 2: Update PR #965**

`gh pr edit 965` — rewrite the body: distribution section now describes the vestad-local model (embed → build-workspace.sh → bundle → loopback endpoint → fetch-workspace.sh), links both specs, drops the branch-protection checklist item entirely, keeps the Parts 1–3 description, and notes the pivot commit range. Then **ask the user** before merging (their explicit-approval preference).

## Self-Review Notes

- Spec coverage: embed widening → Task 1; construction script + tests → Task 2; delivery/fetch + box scripts + fixtures → Task 3; startup wrapper → Task 4; endpoint → Task 5; env-var/`detect_workspace_ref`/pr.py retirement → Task 6; CI deletion → Task 7; integration coverage → Task 8; docs → Task 9; gate → Task 10. Migration contingency softening → Task 3 Step 5. "What carries over" needs no tasks by definition.
- Pivot-inventory check (things already on the branch that this plan explicitly touches): `tools/publish-agent-branch.sh` (T2 delete), `test_publish_agent_branch.py` (T2 delete), attach/status/SKILL.md `VESTA_WORKSPACE_REF`+`VESTA_UPSTREAM_URL` usage (T3), migration "remote" wording (T3), `detect_workspace_ref` + env writer/updater + its docker.rs test (T6), `pr.py`/upstream-pr SKILL.md env reads (T6), ci.yml publish job + three `needs:` lists (T7), CLAUDE.md paragraph + invariant sentence (T9), PR body checklist item (T10). Unchanged by design: `workspace_sync.py`, tools.py, boot wiring, migration flow structure, engine move, mounts/entrypoint, `test_workspace_sync_turn.py`, layout.rs's `workspace-sync` symlink assertion.
- Startup is fatal on a missing bundle: both `ensure_agent_code` and `ensure_workspace` abort startup (`std::process::exit(1)`, like `validate_config_dir`) if they fail. A vestad that can't build the workspace bundle can't let any box attach, sync, or install skills, so it refuses to serve a half-broken daemon rather than 404ing every box silently. (Originally drafted loud-but-nonfatal; reversed on review — a broken workspace feature is worse than a fast, obvious failure.)
- Transient red: only between Tasks 2 and 3 (box-flow fixtures reference the moved script) — execute back-to-back.
