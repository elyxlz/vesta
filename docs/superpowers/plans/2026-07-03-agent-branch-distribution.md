# Agent-Branch Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade-driven upstream sync (boot turn + mark tool), `upstream-sync` as a core skill, `pyproject.toml`/`uv.lock` moved into `core/`, and fleet distribution via a CI-published agent branch with version-pinned rebase sync.

**Architecture:** A CI job publishes the complete agent home (engine + skills) to an append-only `agent-workspace` branch, one commit + `agent-vX.Y.Z` tag per release. Boxes attach once (cone-mode sparse checkout, standard porcelain), then sync by rebasing local changes onto the snapshot tag matching their running core version, triggered by an upgrade boot turn that re-fires until a `mark_upstream_synced` tool records success. Managed boxes get core via one read-only mount; unmanaged boxes add `agent/core` to their checkout cone.

**Tech Stack:** Python 3.12 (uv, pydantic, pytest), Rust (vestad, bollard), bash + git porcelain, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-03-upgrade-upstream-sync-design.md` — read it before starting any task.

## Global Constraints

- Python: always `uv run`, never bare `python`. No `getattr`/dict-`.get()` fallback/`hasattr`. No blocking calls in coroutines. Line length 144 (ruff). Log with `%`-style placeholders.
- Rust: no `panic!`/`unwrap`/`expect` on fallible paths; named consts for magic values; descriptive names.
- Copy/prose: the agent is "Vesta" or "they/them", never "she/it".
- Conventional Commits subjects, imperative, no trailing period. **No version bumps.**
- Skills index: after any skill add/move/edit run `uv run python agent/skills/generate-index.py` (from repo root) and commit `agent/skills/index.json`.
- Transitional code carries `LEGACY(remove-when: <condition>): <what/why>` markers.
- Branch name: `agent-workspace`. Snapshot tags: `agent-vX.Y.Z`. Remote URL on boxes: `https://github.com/elyxlz/vesta.git`.
- All work happens on the existing branch `feat/agent-branch-distribution`; one commit per task.
- Tests must not depend on network, Docker, or a running agent (except suites already gated that way).

---

### Task 1: Move pyproject.toml + uv.lock into core/; split dev-tool configs; update check.sh

The agent Python project is deps-only (no build system), so the move needs no code restructuring — only path plumbing. Tool configs (`[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.ty.*]`) can't stay in the moved pyproject (their relative paths anchor to the file's directory, and tools discover config from cwd upward), so they split into dedicated dev-only files at `agent/` which the publish job (Task 6) simply never includes.

**Files:**
- Move: `agent/pyproject.toml` → `agent/core/pyproject.toml` (deps only)
- Move: `agent/uv.lock` → `agent/core/uv.lock`
- Create: `agent/ruff.toml`
- Create: `agent/pytest.ini`
- Create: `agent/ty.toml`
- Modify: `check.sh` (check_agent)
- Modify: `agent/core/main.py:241` (`_vesta_version` pyproject path)

**Interfaces:**
- Produces: engine project at `agent/core/pyproject.toml` (version line format unchanged: `version = "X.Y.Z"`); shared venv at `agent/.venv` via `UV_PROJECT_ENVIRONMENT`; `check.sh agent` green under the new layout. Later tasks read the version from `<agent_dir>/core/pyproject.toml`.

- [ ] **Step 1: Move the files and strip tool sections**

```bash
cd /Users/epasca/vesta
git mv agent/pyproject.toml agent/core/pyproject.toml
git mv agent/uv.lock agent/core/uv.lock
```

Edit `agent/core/pyproject.toml`: delete the `[tool.pytest.ini_options]`, `[tool.ty.src]`, `[tool.ty.environment]`, `[tool.ruff]`, `[tool.ruff.lint]` sections entirely (keep `[project]`, `[project.urls]`, `[dependency-groups]`).

- [ ] **Step 2: Create the dev-tool config files**

`agent/ruff.toml`:
```toml
line-length = 144
indent-width = 4
target-version = "py312"

[lint]
ignore = ["E402", "E702", "E731", "UP008", "E712"]
extend-select = ["UP"]
```

`agent/pytest.ini`:
```ini
[pytest]
python_files = test_*.py *_test.py
testpaths = tests
pythonpath = . skills
; Per-test hard timeout: a hung async test fails fast instead of hanging CI until the job timeout.
timeout = 120
```

`agent/ty.toml`:
```toml
[src]
include = ["core", "tests"]

[environment]
extra-paths = ["skills", "core/skills/app-chat/cli/src"]
```

- [ ] **Step 3: Update check.sh's agent suite**

Replace the `check_agent()` body in `check.sh`:

```bash
check_agent() {
  (
    cd agent
    # The engine project lives at core/ (published to boxes); dev-tool configs
    # (ruff.toml, pytest.ini, ty.toml) live here and are never published.
    export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
    uv run --project core ruff check
    uv run --project core ruff format --check
    uv sync --project core
    for tool in skills/*/cli/; do
      if [ -f "$tool/pyproject.toml" ]; then
        uv pip install -e "$tool"
      fi
    done
    uv run --project core ty check
    uv run --project core pytest tests/ -v
  )
}
```

- [ ] **Step 4: Fix `_vesta_version` path in main.py**

In `agent/core/main.py` (`_vesta_version`), change:
```python
    pyproject = config.agent_dir / "pyproject.toml"
```
to:
```python
    pyproject = config.agent_dir / "core" / "pyproject.toml"
```
Also update its docstring's "bind-mounted pyproject.toml" wording to "pyproject.toml inside the bind-mounted core". (Task 4 moves this function; the path must be correct now so this task is green.)

- [ ] **Step 5: Sweep for stale path references in agent/**

```bash
rg -n 'agent/pyproject|agent_dir / "pyproject|"pyproject.toml"' agent/ --glob '!core/pyproject.toml'
```
Fix any hit that means the old location (tests that construct a fake `pyproject.toml` under `agent_dir` must now write it under `agent_dir/core/`). Do not touch skill CLIs' own `cli/pyproject.toml` files.

- [ ] **Step 6: Run the agent suite**

Run: `./check.sh agent`
Expected: PASS (ruff, format, ty, pytest all green under the new layout).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(agent): move pyproject.toml and uv.lock into core/, split dev-tool configs"
```

---

### Task 2: vestad — single engine mount, dual-layout entrypoint, embed/build paths, detect_upstream_ref

**Files:**
- Modify: `vestad/src/docker.rs` (`MOUNT_DESTS` ~:98, `agent_container_entrypoint_cmd` ~:100-135, `create_container` ~:1420-1445, `detect_upstream_ref` ~:878, `mounts_have_core_code`, tests ~:2260-2290 and ~:2830-2860)
- Modify: `vestad/src/agent_embed.rs` (drop two include lines)
- Modify: `vestad/build.rs:75` (hash inputs)
- Modify: `vestad/Dockerfile` (uv sync + env)

**Interfaces:**
- Consumes: engine layout from Task 1 (`agent/core/pyproject.toml`, `agent/core/uv.lock`).
- Produces: `MOUNT_DESTS = [ENV_MOUNT_DEST, CORE_MOUNT_DEST, CONSTITUTION_MOUNT_DEST]`; env var `VESTA_UPSTREAM_REF` = `"agent-workspace"` in release builds and `"agent-workspace-<git branch>"` in dev builds; entrypoint exports `UV_PROJECT_ENVIRONMENT=/root/agent/.venv`.

- [ ] **Step 1: Collapse the mounts**

In `docker.rs`:
```rust
pub(crate) const MOUNT_DESTS: &[&str] = &[ENV_MOUNT_DEST, CORE_MOUNT_DEST, CONSTITUTION_MOUNT_DEST];
```
In `create_container`, delete the `pyproject_mount` and `lock_mount` lines and shrink the managed bind to:
```rust
    if manage_core_code {
        binds.push(core_mount);
    }
```
Fix every `MOUNT_DESTS[n]` index use accordingly (`rg -n 'MOUNT_DESTS\[' vestad/src`).

- [ ] **Step 2: Dual-layout entrypoint + venv pin + LEGACY markers**

In `agent_container_entrypoint_cmd`, change three steps (array size changes from 10 to 11):

Add as a new step right after the PATH export:
```rust
        // The venv must live outside the read-only core mount (uv would default to
        // /root/agent/core/.venv, inside it).
        "export UV_PROJECT_ENVIRONMENT=/root/agent/.venv".into(),
```

Replace `"uv sync --frozen --project /root/agent".into(),` with:
```rust
        // LEGACY(remove-when: unmanaged boxes have pulled a post-engine-move snapshot):
        // unmanaged boxes keep the old layout (pyproject at /root/agent) until they rebase
        // onto an agent-v* snapshot; tolerate both so they never crash-loop.
        "if [ -f /root/agent/core/pyproject.toml ]; then uv sync --frozen --project /root/agent/core; else uv sync --frozen --project /root/agent; fi".into(),
```

Replace the final launch step with:
```rust
        "cd /root/agent && if [ -f core/pyproject.toml ]; then exec uv run --frozen --project core python -m core.main; else exec uv run --frozen python -m core.main; fi".into(),
```

On the existing `.claude` untrack step's comment block, prepend:
```rust
        // LEGACY(remove-when: fleet converged to agent-branch workspaces — the published
        // branch never tracks .claude, so migrated workspaces cannot hit this):
```

- [ ] **Step 3: detect_upstream_ref → agent branch**

```rust
/// Compute the fetch target for the agent's workspace: the published agent branch.
/// Boxes derive their snapshot tag (`agent-v<version>`) themselves from the core
/// version they run.
///
/// Dev builds: a per-branch dev agent branch (`agent-workspace-<branch>`), published
/// manually with tools/publish-agent-branch.sh when exercising the sync flow itself.
/// Release builds: the fleet branch.
pub fn detect_upstream_ref() -> Option<String> {
    if cfg!(debug_assertions) {
        let output = std::process::Command::new("git")
            .args(["rev-parse", "--abbrev-ref", "HEAD"])
            .output()
            .ok()?;
        if !output.status.success() {
            return None;
        }
        let branch = String::from_utf8(output.stdout).ok()?.trim().to_string();
        if branch.is_empty() || branch == "HEAD" {
            return None;
        }
        Some(format!("agent-workspace-{branch}"))
    } else {
        Some("agent-workspace".to_string())
    }
}
```

- [ ] **Step 4: mounts_have_core_code accepts both shapes**

Find the function (`rg -n 'fn mounts_have_core_code' vestad/src/docker.rs`). Make it return true iff any mount's destination equals `CORE_MOUNT_DEST` (the legacy three-mount shape also has that mount, so old restic backups restore as managed). If it already keys only on `CORE_MOUNT_DEST`, leave it and just add the test below.

- [ ] **Step 5: agent_embed.rs and build.rs**

`vestad/src/agent_embed.rs`: delete the `#[include = "pyproject.toml"]` and `#[include = "uv.lock"]` lines (`core/**/*` now covers both files post-move).

`vestad/build.rs:75`: change
```rust
    for rel in ["agent/core", "agent/pyproject.toml", "agent/uv.lock"] {
```
to
```rust
    for rel in ["agent/core"] {
```

- [ ] **Step 6: Dockerfile**

In `vestad/Dockerfile` replace:
```dockerfile
WORKDIR /root/agent
RUN uv sync --frozen --no-install-project
```
with:
```dockerfile
ENV UV_PROJECT_ENVIRONMENT=/root/agent/.venv
WORKDIR /root/agent
RUN uv sync --frozen --no-install-project --project core
```

- [ ] **Step 7: Update vestad unit tests**

- The container tests around `docker.rs:2830-2860` that create dummy `pyproject.toml`/`uv.lock` in `code_dir` and assert the three engine binds: change to a single `CORE_MOUNT_DEST` bind assertion (dummy files now under `code_dir/core/`).
- Entrypoint tests (~:2260-2290): update the launch-step assertions to match the dual-layout string (`script.find("python -m core.main")` still works; add an assertion that the script contains `UV_PROJECT_ENVIRONMENT=/root/agent/.venv` and `--project /root/agent/core`).
- Add a test for `mounts_have_core_code`:

```rust
    #[test]
    fn mounts_have_core_code_accepts_legacy_and_single_mount_shapes() {
        let single = vec![mount_with_dest(CORE_MOUNT_DEST)];
        let legacy = vec![
            mount_with_dest(CORE_MOUNT_DEST),
            mount_with_dest("/root/agent/pyproject.toml"),
            mount_with_dest("/root/agent/uv.lock"),
        ];
        let none = vec![mount_with_dest(ENV_MOUNT_DEST)];
        assert!(mounts_have_core_code(&single));
        assert!(mounts_have_core_code(&legacy));
        assert!(!mounts_have_core_code(&none));
    }
```
(`mount_with_dest` = whatever helper/struct literal the surrounding tests already use for `bollard::models::MountPoint`; match the existing pattern.)

- Add a test that `detect_upstream_ref` in debug builds returns a value starting with `agent-workspace-` (guard with `#[cfg(debug_assertions)]`).

- [ ] **Step 8: Run vestad suite**

Run: `./check.sh vestad`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add vestad/
git commit -m "feat(vestad): single engine mount, dual-layout entrypoint, agent-workspace upstream ref"
```

---

### Task 3: CI / release plumbing paths

**Files:**
- Modify: `.github/workflows/ci.yml` (version-check greps :91,:135; lockfile job ~:188-210)
- Modify: `.github/workflows/release.yml` (sed at :72)
- `.github/dependabot.yml`: leave `directory: /agent` **unchanged** — verify note below.

**Interfaces:**
- Consumes: `agent/core/pyproject.toml` from Task 1.

- [ ] **Step 1: ci.yml version-check**

Change both greps that read `agent/pyproject.toml` (lines ~91 and ~135) to `agent/core/pyproject.toml`.

- [ ] **Step 2: ci.yml lockfile job**

The job runs `uv lock` against the agent project (working directory `agent`, ~lines 195-210). Change the lock invocation to `uv lock --project core`, the `cp`/`diff` paths to `core/uv.lock`, and the failure message to `Please run 'cd agent && uv lock --project core' locally and commit the changes`.

- [ ] **Step 3: release.yml bump**

Line ~72: `sed -i ... agent/pyproject.toml` → `agent/core/pyproject.toml`.

- [ ] **Step 4: dependabot**

`pip` ecosystem `directory` must point at the directory containing the manifest: change `/agent` → `/agent/core`.

- [ ] **Step 5: Repo-wide stale-path sweep**

```bash
rg -n 'agent/pyproject\.toml|agent/uv\.lock' --glob '!docs/**' --glob '!*.lock'
```
Every remaining hit must be either (a) intentionally legacy-tolerant (the entrypoint shim from Task 2), or (b) fixed. Check `vestad/tests/` (layout assertions) and `.github/workflows/*` in particular.

- [ ] **Step 6: Commit**

```bash
git add .github/ && git add -u
git commit -m "build(ci): point version, lockfile and release plumbing at agent/core"
```

---

### Task 4: upgrade_sync module + persisted version marker (Part 1)

**Files:**
- Create: `agent/core/upgrade_sync.py`
- Modify: `agent/core/state_store.py:31-37` (`PersistedState`)
- Modify: `agent/core/main.py` (delete `_vesta_version`, import from upgrade_sync)
- Test: `agent/tests/test_upgrade_sync.py`

**Interfaces:**
- Produces:
  - `upgrade_sync.vesta_version(config: vm.VestaConfig) -> str` — running core version or `"unknown"`; never raises.
  - `upgrade_sync.upgrade_sync_turn(*, state: vm.State, config: vm.VestaConfig, first_start: bool) -> str | None` — boot-turn body or None; on first start pre-marks and returns None.
  - `PersistedState.last_synced_version: str | None = None`.
- Consumed by: Task 5 (`collect_boot_turns`, `mark_upstream_synced`).

- [ ] **Step 1: Add the state field**

In `agent/core/state_store.py`, add to `PersistedState`:
```python
    last_synced_version: str | None = None
```

- [ ] **Step 2: Write the failing tests**

`agent/tests/test_upgrade_sync.py`:
```python
"""Upgrade-driven upstream sync: version marker + boot turn (spec Part 1)."""

import core.models as vm
from core import state_store
from core.upgrade_sync import upgrade_sync_turn, vesta_version


def _config(tmp_path, version: str | None = "0.1.170") -> vm.VestaConfig:
    config = vm.VestaConfig(agent_dir=tmp_path / "agent")
    (config.agent_dir / "core").mkdir(parents=True, exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    if version is not None:
        (config.agent_dir / "core" / "pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    return config


def test_vesta_version_reads_core_pyproject(tmp_path):
    assert vesta_version(_config(tmp_path, "0.1.170")) == "0.1.170"


def test_vesta_version_unknown_when_missing_or_broken(tmp_path):
    assert vesta_version(_config(tmp_path, version=None)) == "unknown"
    config = _config(tmp_path, version=None)
    (config.agent_dir / "core" / "pyproject.toml").write_text("not toml [")
    assert vesta_version(config) == "unknown"


def test_turn_fires_on_version_mismatch_and_names_the_snapshot(tmp_path):
    config = _config(tmp_path, "0.1.171")
    state = vm.State()
    state.persisted.last_synced_version = "0.1.170"
    turn = upgrade_sync_turn(state=state, config=config, first_start=False)
    assert turn is not None
    assert "agent-v0.1.171" in turn
    assert "mark_upstream_synced" in turn


def test_turn_fires_when_marker_absent_legacy_agent(tmp_path):
    state = vm.State()
    assert state.persisted.last_synced_version is None
    assert upgrade_sync_turn(state=state, config=_config(tmp_path), first_start=False) is not None


def test_no_turn_when_versions_match(tmp_path):
    state = vm.State()
    state.persisted.last_synced_version = "0.1.170"
    assert upgrade_sync_turn(state=state, config=_config(tmp_path, "0.1.170"), first_start=False) is None


def test_no_turn_when_version_unknown_and_nothing_marked(tmp_path):
    state = vm.State()
    assert upgrade_sync_turn(state=state, config=_config(tmp_path, version=None), first_start=False) is None
    assert state.persisted.last_synced_version is None


def test_first_start_pre_marks_and_returns_none(tmp_path):
    config = _config(tmp_path, "0.1.170")
    state = vm.State()
    assert upgrade_sync_turn(state=state, config=config, first_start=True) is None
    assert state.persisted.last_synced_version == "0.1.170"
    assert state_store.load_state(config).last_synced_version == "0.1.170"


def test_first_start_with_unknown_version_marks_nothing(tmp_path):
    state = vm.State()
    assert upgrade_sync_turn(state=state, config=_config(tmp_path, version=None), first_start=True) is None
    assert state.persisted.last_synced_version is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd agent && uv run --project core pytest tests/test_upgrade_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.upgrade_sync'`.

- [ ] **Step 4: Implement `agent/core/upgrade_sync.py`**

```python
"""Upgrade-driven upstream sync trigger.

A vestad upgrade re-extracts the core mount, so the running core version (read from
core/pyproject.toml) changes across the restart. This module turns that signal into a
boot turn: when the persisted `last_synced_version` doesn't match the running version,
the agent is told to rebase its workspace onto this version's published snapshot
(`agent-v<version>` on the agent branch) and record completion via the
`mark_upstream_synced` tool. Unmarked (failed, crashed, forgotten) turns re-fire on
every boot until the sync lands — the flow itself is idempotent.

Fresh agents pre-mark the current version without a turn (the image is already
current), the same pattern migrations use. An unreadable version never fires and never
marks: no churn on a broken pyproject.
"""

import tomllib

from . import logger
from . import models as vm
from . import state_store

UNKNOWN_VERSION = "unknown"


def vesta_version(config: vm.VestaConfig) -> str:
    """Version of the code actually running, read from core/pyproject.toml (re-extracted on
    upgrade, so it tracks the running core). Best-effort: never raises over a version label."""
    pyproject = config.agent_dir / "core" / "pyproject.toml"
    if not pyproject.exists():
        return UNKNOWN_VERSION
    try:
        return tomllib.loads(pyproject.read_text())["project"]["version"]
    except (tomllib.TOMLDecodeError, KeyError, OSError) as e:
        logger.init(f"could not read version: {e}")
        return UNKNOWN_VERSION


def upgrade_sync_turn(*, state: vm.State, config: vm.VestaConfig, first_start: bool) -> str | None:
    """Boot-turn body telling the agent to sync onto this version's snapshot, or None.

    First start pre-marks the running version (fresh image is already current). An
    unknown version is never acted on. Any mismatch — including an absent marker on a
    legacy agent, and downgrades — fires the turn."""
    running = vesta_version(config)
    if running == UNKNOWN_VERSION:
        return None
    if first_start:
        state.persisted.last_synced_version = running
        state_store.save_state(state.persisted, config)
        return None
    if state.persisted.last_synced_version == running:
        return None
    logger.startup(f"Queued upstream-sync boot turn: {state.persisted.last_synced_version} -> {running}")
    return (
        "[Upstream sync]\n\n"
        f"Vesta was upgraded (now v{running}). Read `~/agent/core/skills/upstream-sync/SKILL.md` "
        f"and follow it to bring your workspace to this version's snapshot: rebase your changes "
        f"onto `agent-v{running}`, resolving any conflicts. Then call `mark_upstream_synced`. "
        "If the rebase brought changes, call `restart_vesta` afterward so updated skills load; "
        "if it was a no-op, no restart is needed. If it fails, tell the user what blocked it."
    )
```

- [ ] **Step 5: Move main.py onto it**

In `agent/core/main.py`: delete the `_vesta_version` function and the `tomllib` import; add `from .upgrade_sync import vesta_version`; change the caller:
```python
    logger.init(f"{config.agent_name} starting on vesta v{vesta_version(config)}")
```

- [ ] **Step 6: Run tests**

Run: `cd agent && uv run --project core pytest tests/test_upgrade_sync.py tests/test_boot_turns.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add agent/core/upgrade_sync.py agent/core/state_store.py agent/core/main.py agent/tests/test_upgrade_sync.py
git commit -m "feat(agent): upgrade-driven upstream-sync boot turn with persisted version marker"
```

---

### Task 5: mark_upstream_synced tool + boot-turn wiring

**Files:**
- Modify: `agent/core/tools.py` (new tool; register in the returned list)
- Modify: `agent/core/main.py:188-205` (`collect_boot_turns`)
- Test: `agent/tests/test_upgrade_sync.py` (tool test), `agent/tests/test_boot_turns.py` (ordering)

**Interfaces:**
- Consumes: `upgrade_sync.upgrade_sync_turn`, `upgrade_sync.vesta_version` (Task 4).
- Produces: MCP tool `mark_upstream_synced` (no args) recording `vesta_version(config)` into `persisted.last_synced_version`. Boot order: migrations → upstream sync → default-skill sync → config issues → greeting.

- [ ] **Step 1: Write the failing tests**

Append to `agent/tests/test_upgrade_sync.py`:
```python
import asyncio

from core.tools import _vesta_tools


def test_mark_upstream_synced_records_running_version(tmp_path):
    config = _config(tmp_path, "0.1.171")
    state = vm.State()
    state.persisted.last_synced_version = "0.1.170"
    tools = {t.name: t for t in _vesta_tools(state, config)}
    result = asyncio.run(tools["mark_upstream_synced"].handler({}))
    assert "0.1.171" in result["content"][0]["text"]
    assert state.persisted.last_synced_version == "0.1.171"
    assert state_store.load_state(config).last_synced_version == "0.1.171"
```
(Check how existing tests invoke SDK `@tool` objects — if another test file already calls one, mirror its access pattern for the decorated tool's name/handler; adjust the two attribute accesses only.)

In `agent/tests/test_boot_turns.py`, update `test_boot_turns_ordered_migrations_then_skill_then_config_then_greeting`: inside the test, give the config a versioned core pyproject and an out-of-date marker so the sync turn fires between migrations and skill-sync:
```python
    (config.agent_dir / "core" / "pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "9.9.9"\n')
```
and change the assertions to:
```python
    assert len(turns) == 5
    assert "[Migration: 001-x]" in turns[0]
    assert "[Upstream sync]" in turns[1]
    assert "skills-install alpha" in turns[2]
    assert "BAD=1" in turns[3]
    assert "[System: restart: clean restart]" in turns[4]
```
Also update `test_first_start_pre_marks_migrations_and_greets_with_setup` to assert the version marker was pre-marked when a versioned pyproject exists (add the pyproject write + `assert state.persisted.last_synced_version == "9.9.9"`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && uv run --project core pytest tests/test_upgrade_sync.py tests/test_boot_turns.py -v`
Expected: FAIL — no `mark_upstream_synced` tool; boot turns count 4 != 5.

- [ ] **Step 3: Implement the tool**

In `agent/core/tools.py`, add after `mark_migration_applied` (import `from .upgrade_sync import vesta_version` at top):
```python
    @tool(
        "mark_upstream_synced",
        "Call once the upstream sync completed: the workspace was rebased onto this version's snapshot "
        "(agent-v<version>) and any conflicts are resolved. Records the synced version; without this call "
        "the sync boot turn re-fires on every boot. Call it BEFORE restart_vesta.",
        {},
    )
    async def mark_upstream_synced(args: dict[str, tp.Any]) -> dict[str, tp.Any]:
        version = vesta_version(config)
        state.persisted.last_synced_version = version
        state_store.save_state(state.persisted, config)
        logger.startup(f"Upstream sync marked complete by agent at v{version}")
        return {"content": [{"type": "text", "text": f"synced: {version}"}]}
```
Add it to the returned list:
```python
    return [restart_vesta, stop_vesta, mark_setup_done, mark_migration_applied, mark_upstream_synced, mark_dreamer_complete]
```

- [ ] **Step 4: Wire into collect_boot_turns**

In `agent/core/main.py` add `from .upgrade_sync import upgrade_sync_turn` (extend the Task 4 import line) and insert between migrations and skill sync in `collect_boot_turns`:
```python
    turns.extend(pending_migration_turns(state=state, config=config, first_start=first_start))
    sync_turn = upgrade_sync_turn(state=state, config=config, first_start=first_start)
    if sync_turn is not None:
        turns.append(sync_turn)
    skill_sync = default_skill_sync_turn(config=config, first_start=first_start)
```
Update the function's docstring ordering note to "migrations, then upstream sync, then default-skill sync, then config issues, then the greeting last".

- [ ] **Step 5: Run tests, then the full agent suite**

Run: `cd agent && uv run --project core pytest tests/test_upgrade_sync.py tests/test_boot_turns.py -v` → PASS
Run: `./check.sh agent` → PASS

- [ ] **Step 6: Commit**

```bash
git add agent/core/tools.py agent/core/main.py agent/tests/
git commit -m "feat(agent): mark_upstream_synced tool and boot-turn wiring"
```

---

### Task 6: Publish script (tools/publish-agent-branch.sh) + tests

**Files:**
- Create: `tools/publish-agent-branch.sh`
- Test: `agent/tests/test_publish_agent_branch.py` (lives in the agent suite deliberately: it's the one harness with real-git test utilities, and `check.sh agent` runs it)

**Interfaces:**
- Produces: `publish-agent-branch.sh <source-ref> [branch]` run from a checkout — constructs the filtered agent-home tree from `<source-ref>`, commits it onto `[branch]` (default `agent-workspace`) if changed, tags `agent-v<version>` (version read from `agent/core/pyproject.toml` at the source ref), pushes branch+tag with `git push --atomic origin <branch> refs/tags/agent-v<version>`. Exit 0 on success or no-op; non-zero on non-fast-forward or any failure.
- Consumed by: Task 7 (CI job), Task 9 (box-flow tests use it to build fixture branches).

- [ ] **Step 1: Write the failing tests**

`agent/tests/test_publish_agent_branch.py`:
```python
"""Exercises the REAL publish script against local git repos (no network)."""

import pathlib as pl
import subprocess

import pytest

from test_upstream_sync import BASE_ENV, _env  # reuse the hermetic-git env helpers

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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd agent && uv run --project core pytest tests/test_publish_agent_branch.py -v`
Expected: FAIL — script not found / non-zero.

- [ ] **Step 3: Implement `tools/publish-agent-branch.sh`**

```bash
#!/usr/bin/env bash
# Publish the complete agent home to the fleet branch: one commit + one agent-v<version>
# tag per release, append-only by construction (worktree rebuilt from the source ref and
# committed on top of the existing branch head — history is never rewritten, pushes are
# plain fast-forwards and the branch + tag land atomically or not at all).
#
# Usage: publish-agent-branch.sh <source-ref> [branch]
#   source-ref  commit to publish from (e.g. the release tag)
#   branch      target branch (default: agent-workspace; dev flows publish
#               agent-workspace-<branch>)
#
# Published tree: agent/core (engine incl. pyproject/uv.lock), agent/skills,
# agent/MEMORY.md, agent/.gitignore, plus a script-owned root .gitignore. Nothing else —
# never .claude, never the rest of the monorepo, never dev-tool configs.
set -euo pipefail

SRC_REF="${1:?Usage: publish-agent-branch.sh <source-ref> [branch]}"
BRANCH="${2:-agent-workspace}"
REMOTE="origin"
PUBLISH_PATHS=(agent/core agent/skills agent/MEMORY.md agent/.gitignore)

VERSION="$(git show "$SRC_REF:agent/core/pyproject.toml" | grep '^version = ' | cut -d'"' -f2)"
[ -n "$VERSION" ] || { echo "error: could not read version from $SRC_REF" >&2; exit 1; }
TAG="agent-v$VERSION"
SRC_SHA="$(git rev-parse "$SRC_REF")"

WORK="$(mktemp -d)"
STAGE="$(mktemp -d)"
cleanup() { git worktree remove --force "$WORK" 2>/dev/null || true; rm -rf "$WORK" "$STAGE"; }
trap cleanup EXIT

git archive "$SRC_REF" "${PUBLISH_PATHS[@]}" | tar -x -C "$STAGE"
cat > "$STAGE/.gitignore" <<'EOF'
/*
!/agent/
*.bin
*.onnx
*.pt
*.db
*.sqlite
*.mp3
*.mp4
*.wav
*.zip
*.tar.gz
node_modules/
dist/
.venv/
__pycache__/
EOF

if git fetch "$REMOTE" "$BRANCH" 2>/dev/null; then
  git worktree add "$WORK" FETCH_HEAD
  git -C "$WORK" checkout -B "$BRANCH" FETCH_HEAD
else
  git worktree add --detach "$WORK"
  git -C "$WORK" checkout --orphan "$BRANCH"
  git -C "$WORK" rm -rfq --cached . 2>/dev/null || true
  find "$WORK" -mindepth 1 -maxdepth 1 -not -name .git -exec rm -rf {} +
fi

rsync -a --delete --exclude=.git "$STAGE/" "$WORK/"
git -C "$WORK" add -A
if git -C "$WORK" diff --cached --quiet 2>/dev/null && git -C "$WORK" rev-parse -q --verify HEAD >/dev/null; then
  echo "publish: no content change for v$VERSION; nothing to do"
  exit 0
fi
git -C "$WORK" commit -m "publish v$VERSION from ${SRC_SHA:0:12}"
git -C "$WORK" tag "$TAG"
# Plain push: fast-forward-only by git's default; --atomic lands branch+tag together or not at all.
git -C "$WORK" push --atomic "$REMOTE" "refs/heads/$BRANCH:refs/heads/$BRANCH" "refs/tags/$TAG:refs/tags/$TAG"
echo "publish: $BRANCH -> v$VERSION ($TAG)"
```

```bash
chmod +x tools/publish-agent-branch.sh
```

- [ ] **Step 4: Run tests**

Run: `cd agent && uv run --project core pytest tests/test_publish_agent_branch.py -v`
Expected: PASS. Debug iteratively — worktree/orphan mechanics are the likely rough edge; keep the tests as the contract.

- [ ] **Step 5: Commit**

```bash
git add tools/publish-agent-branch.sh agent/tests/test_publish_agent_branch.py
git commit -m "feat(release): agent-branch publish script with atomic branch+tag push"
```

---

### Task 7: CI release-pipeline wiring for the publish

**Files:**
- Modify: `.github/workflows/ci.yml` (release path)

**Interfaces:**
- Consumes: `tools/publish-agent-branch.sh` (Task 6).
- Produces: on `release` events, ordering test-live → publish-agent-branch → artifact/image publication (artifacts `needs:` the publish job).

- [ ] **Step 1: Map the release job graph**

```bash
rg -n "needs:|if: github.event_name == 'release'|^  [a-z-]+:" .github/workflows/ci.yml
```
Identify: the `test-live` job, and every job that publishes release artifacts or the `:latest` image (they currently `needs:` test-live directly or transitively).

- [ ] **Step 2: Add the publish job**

Add to `ci.yml` (adjust `needs:` to the actual test-live job name found in Step 1):

```yaml
  publish-agent-branch:
    if: github.event_name == 'release'
    needs: [test-live]
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Publish agent branch + snapshot tag
        run: bash tools/publish-agent-branch.sh "${{ github.event.release.tag_name }}"
```

Then add `publish-agent-branch` to the `needs:` list of every artifact/image-publishing release job found in Step 1, so nothing publishes unless the branch push succeeded.

- [ ] **Step 3: Validate workflow syntax**

Run: `gh workflow view CI --ref feat/agent-branch-distribution 2>/dev/null || python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml')); print('yaml ok')"`
Expected: `yaml ok` (full behavior is only exercisable on a real release; the script itself is covered by Task 6's tests).

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "build(ci): publish agent branch before release artifacts, gated on test-live"
```

---

### Task 8: upstream-sync as a core skill — attach script, install/remove, SKILL.md

**Files:**
- Create: `agent/core/skills/upstream-sync/SKILL.md`
- Create: `agent/core/skills/upstream-sync/scripts/attach.sh`
- Create: `agent/core/skills/upstream-sync/scripts/status.sh`
- Rewrite: `agent/skills/skills-registry/scripts/skills-install`
- Create: `agent/skills/skills-registry/scripts/skills-remove`
- Delete: `agent/skills/upstream-sync/` (entire directory: SKILL.md, SETUP.md, scripts/init.sh, sync.sh, status.sh, narrow-sparse-checkout.sh)
- Modify: `agent/core/default-skills.txt` (remove the `upstream-sync` line)
- Regenerate: `agent/skills/index.json`

**Interfaces:**
- Consumes: branch/tag layout from Task 6; `VESTA_UPSTREAM_REF` + `AGENT_NAME` env; version at `~/agent/core/pyproject.toml`.
- Produces:
  - `attach.sh` — idempotent; exit 0 attached/already-attached, exit 3 snapshot tag missing, exit 4 legacy workspace detected (migration needed). Optional env `VESTA_UPSTREAM_URL` overrides the remote URL (tests use a local path).
  - `skills-install <name>` — exit 0 installed/already-installed, exit 1 unknown skill.
  - `skills-remove <name>` — exit 0 removed/not-installed.
  - Sync itself is raw porcelain documented in SKILL.md (no sync.sh): checkpoint commit → `git fetch origin` → `git rebase agent-v<version>`.
- Note: Task 9 writes the tests for all of these; this task only hand-smoke-tests. Implement both tasks back-to-back.

- [ ] **Step 1: attach.sh**

`agent/core/skills/upstream-sync/scripts/attach.sh`:
```bash
#!/usr/bin/env bash
# Attach $HOME to the published agent branch. Idempotent and worktree-safe: the only
# working-tree-touching step is `git reset --mixed`, which never writes files, so local
# content can never be clobbered — differences just show up in `git status` afterwards.
#
# Exit: 0 attached (or already attached); 3 snapshot tag for the running version not
# found on the remote; 4 legacy workspace detected (follow the migration flow in
# SKILL.md: back up, retire ~/.git, re-run).
set -euo pipefail

REF="${VESTA_UPSTREAM_REF:?VESTA_UPSTREAM_REF is unset (source /run/vestad-env)}"
NAME="${AGENT_NAME:?AGENT_NAME is unset (source /run/vestad-env)}"
URL="${VESTA_UPSTREAM_URL:-https://github.com/elyxlz/vesta.git}"
cd ~

VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"

if [ -d .git ]; then
  # Legacy shape: the pre-branch workspace used hand-built no-cone sparse patterns.
  if [ -f .git/info/sparse-checkout ] && grep -q '^!' .git/info/sparse-checkout 2>/dev/null; then
    echo "legacy workspace detected: follow the migration flow in SKILL.md" >&2
    exit 4
  fi
else
  git init -b "$NAME"
fi

git remote get-url origin >/dev/null 2>&1 || git remote add origin "$URL"
git remote set-url origin "$URL"
# Fetch exactly the agent branch + snapshot tags; never the monorepo's branches or
# release tags (those would drag master history onto the box).
git config remote.origin.tagOpt --no-tags
git config --unset-all remote.origin.fetch 2>/dev/null || true
git config remote.origin.fetch "+refs/heads/$REF:refs/remotes/origin/$REF"
git config --add remote.origin.fetch '+refs/tags/agent-v*:refs/tags/agent-v*'
git config user.name "$NAME"
git config user.email "$NAME@vesta"

git fetch origin
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || {
  echo "snapshot $TAG not found on $REF - was this release published?" >&2
  exit 3
}

# Cone = the skills on disk (installed set) — engine and uninstalled skills stay out.
find agent/skills -mindepth 1 -maxdepth 1 -type d | sort | git sparse-checkout set --cone --stdin

if ! git rev-parse -q --verify HEAD >/dev/null; then
  git update-ref "refs/heads/$NAME" "$TAG"
  git reset --mixed   # load index from the snapshot; worktree untouched
fi
echo "attached: branch $NAME on $TAG"
```

- [ ] **Step 2: status.sh**

`agent/core/skills/upstream-sync/scripts/status.sh`:
```bash
#!/usr/bin/env bash
# Read-only: where this box stands vs its version's snapshot and the branch tip.
set -euo pipefail
cd ~
REF="${VESTA_UPSTREAM_REF:?VESTA_UPSTREAM_REF is unset}"
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"
git fetch origin
echo "== running core: v$VERSION (snapshot $TAG)"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "== my changes on top of $TAG:"
  git log --oneline "$TAG..HEAD" || true
else
  echo "== snapshot $TAG not found on $REF"
fi
echo "== branch tip:"
git log --oneline -1 "refs/remotes/origin/$REF" 2>/dev/null || echo "(not fetched)"
```

- [ ] **Step 3: Rewrite skills-install, add skills-remove**

`agent/skills/skills-registry/scripts/skills-install`:
```bash
#!/usr/bin/env bash
# Install a skill: add its directory to the sparse-checkout cone. Instant and offline —
# the content is already in the local branch history from the last sync/attach.
set -euo pipefail
SKILL_NAME="${1:?Usage: skills-install <skill-name>}"
cd ~
DEST="agent/skills/$SKILL_NAME"

if [ -d "$DEST" ]; then
    echo "Skill '$SKILL_NAME' is already installed."
    exit 0
fi

# Self-init a virgin workspace (no-op when already attached).
bash ~/agent/core/skills/upstream-sync/scripts/attach.sh

git sparse-checkout add "$DEST"
if [ ! -d "$DEST" ]; then
    # Unknown skill: drop the dead cone entry again.
    git sparse-checkout list | grep -vx "$DEST" | git sparse-checkout set --cone --stdin
    echo "Error: skill '$SKILL_NAME' not found in the registry (agent/skills/index.json lists all)." >&2
    exit 1
fi

echo "Installed '$SKILL_NAME'. Restart Vesta to activate it."
if [ -f "$DEST/SETUP.md" ]; then
    echo "This skill requires setup, read $DEST/SETUP.md for instructions."
fi
```

`agent/skills/skills-registry/scripts/skills-remove`:
```bash
#!/usr/bin/env bash
# Uninstall a skill: drop its directory from the sparse-checkout cone. Files leave the
# disk; the content stays in history and reinstalling is instant.
set -euo pipefail
SKILL_NAME="${1:?Usage: skills-remove <skill-name>}"
cd ~
DEST="agent/skills/$SKILL_NAME"
if ! git sparse-checkout list 2>/dev/null | grep -qx "$DEST"; then
    echo "Skill '$SKILL_NAME' is not installed."
    exit 0
fi
git sparse-checkout list | grep -vx "$DEST" | git sparse-checkout set --cone --stdin
echo "Removed '$SKILL_NAME'. Restart Vesta to deactivate it."
```

```bash
chmod +x agent/core/skills/upstream-sync/scripts/*.sh agent/skills/skills-registry/scripts/skills-install agent/skills/skills-registry/scripts/skills-remove
```

- [ ] **Step 4: SKILL.md**

`agent/core/skills/upstream-sync/SKILL.md`:
```markdown
---
name: upstream-sync
description: Sync your workspace with the published agent branch after an upgrade; install core updates on unmanaged boxes; resolve rebase conflicts; one-time legacy migration.
---

# Upstream Sync

Your home is a git checkout of the published agent branch (`$VESTA_UPSTREAM_REF`). Each
release publishes one snapshot commit tagged `agent-vX.Y.Z`. You sync by rebasing your
local changes onto the snapshot matching the core version you are running — your changes
always stay on top. To contribute changes back, see
`~/agent/skills/upstream-pr/SKILL.md`.

Your running version: `grep '^version = ' ~/agent/core/pyproject.toml`

## Sync (after an upgrade, when the boot turn asks)

```bash
cd ~
git add -A && git commit -m checkpoint    # only if `git status` shows changes
git fetch origin
git rebase agent-vX.Y.Z                   # the version from the boot turn
```

- Conflicts: edit each conflicted file so both sides survive, `git add <file>`, then
  `git rebase --continue`. `git rebase --abort` restores exactly the pre-sync state.
- For `agent/MEMORY.md`, keep your accumulated knowledge and adopt upstream's structure.
- Then call `mark_upstream_synced`. If the rebase brought changes, call `restart_vesta`
  (after marking) so updated skills load.
- If the workspace was never set up, run
  `~/agent/core/skills/upstream-sync/scripts/attach.sh` first (idempotent; exit 4 means
  follow Migration below).

## Status

`~/agent/core/skills/upstream-sync/scripts/status.sh` — your delta vs your snapshot,
and the branch tip. Read-only.

## Unmanaged core (only if this box manages its own core)

On boxes created with `--no-manage-core-code`, core is part of your checkout and updates
only when the user asks:

```bash
git sparse-checkout add agent/core        # once, ever
git fetch origin
git rebase agent-vX.Y.Z                   # target release: core + skills move together
```

Restart afterwards. Moving to an OLDER release transplants your delta instead:
`git rebase --onto agent-vOLD agent-vCURRENT` (also the recovery command if the branch
was ever republished).

## Tidy-up (occasionally, e.g. during a dream)

Collapse your commit pile into one readable customizations commit:

```bash
git reset --soft agent-vX.Y.Z             # your current base tag; files untouched
git commit -m "my customizations"
```

## Migration (one-time: legacy workspace, attach.sh exits 4)

Old workspaces used hand-built sparse patterns against the monorepo. Convert once:

```bash
tar czf ~/agent-backup.tar.gz agent       # safety net — keep until verified
ls ~/agent/skills > /tmp/installed-skills # what installed means today
mv ~/.git ~/.git-legacy                   # retire the old repo (delete on a later dream)
~/agent/core/skills/upstream-sync/scripts/attach.sh
git status                                # your personalizations vs stock — judge each:
                                          # keep yours, take stock, or integrate both
rm -f ~/agent/pyproject.toml ~/agent/uv.lock   # stale leftovers of the engine move
git add -A && git commit -m "migrated: local customizations"
```

Then `mark_upstream_synced` and restart. Re-running any of this is safe: attach.sh is
idempotent and a converted workspace no longer matches the legacy shape.
```

- [ ] **Step 5: Delete the old skill, update default-skills.txt, regenerate index**

```bash
git rm -r agent/skills/upstream-sync
```
Edit `agent/core/default-skills.txt`: delete the `upstream-sync` line.
```bash
uv run python agent/skills/generate-index.py
```

- [ ] **Step 6: Smoke-test the scripts parse**

Run: `bash -n agent/core/skills/upstream-sync/scripts/attach.sh agent/core/skills/upstream-sync/scripts/status.sh agent/skills/skills-registry/scripts/skills-install agent/skills/skills-registry/scripts/skills-remove`
Expected: silence (syntax OK). Behavioral coverage lands in Task 9 — run Task 9 immediately after; the agent pytest suite is red between the two tasks (old `test_upstream_sync.py` references deleted scripts).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(skills): upstream-sync becomes a core skill with attach/porcelain flow"
```

---

### Task 9: Box-flow tests — rewrite test_upstream_sync.py

**Files:**
- Rewrite: `agent/tests/test_upstream_sync.py` (replace entirely; keep the module docstring spirit, the `BASE_ENV`/`_env` helpers, and the `pytestmark` skipif — Task 6's test file imports them from here)
- Modify: `agent/tests/test_deployment.py` (expected-skills list)
- Modify: `agent/tests/test_default_skills.py` (only if it references `upstream-sync`; check)

**Interfaces:**
- Consumes: `tools/publish-agent-branch.sh` (fixture builder), `attach.sh`, `skills-install`, `skills-remove`.

- [ ] **Step 1: Rewrite the test module**

Replace `agent/tests/test_upstream_sync.py` with the new harness. Keep these exact helpers so `test_publish_agent_branch.py`'s imports stay valid: `BASE_ENV`, `_env`, plus the `pytestmark` skipif on git/tar. New top:

```python
"""Exercises the REAL agent-branch box flow against local git repos (no network).

Fixtures build a stand-in published branch with the REAL publish script, then drive the
REAL attach.sh / skills-install / skills-remove scripts plus the documented raw porcelain
(checkpoint + fetch + rebase) in a fake $HOME, pinning the assumptions the fleet relies
on: worktree-safe attach, version-pinned rebase, cone scoping (engine and uninstalled
skills stay off disk), offline installs, downgrades, and the legacy-migration spine.
"""
```

Fixture builders (complete code):

```python
AGENT_ROOT = pl.Path(__file__).resolve().parents[1]
REPO_ROOT = AGENT_ROOT.parent
PUBLISH = REPO_ROOT / "tools/publish-agent-branch.sh"
ATTACH = AGENT_ROOT / "core/skills/upstream-sync/scripts/attach.sh"
SKILLS_INSTALL = AGENT_ROOT / "skills/skills-registry/scripts/skills-install"
SKILLS_REMOVE = AGENT_ROOT / "skills/skills-registry/scripts/skills-remove"
BRANCH = "agent-workspace"


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


def _write_monorepo_content(src, version):
    (src / "agent/core").mkdir(parents=True, exist_ok=True)
    (src / "agent/core/pyproject.toml").write_text(f'[project]\nname = "vesta"\nversion = "{version}"\n')
    (src / "agent/core/loops.py").write_text(f"# core at {version}\n")
    for skill in ("tasks", "dream", "whatsapp"):
        d = src / "agent/skills" / skill
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(f"---\nname: {skill}\ndescription: {skill} at {version}\n---\n")
    (src / "agent/MEMORY.md").write_text(f"# memory template {version}\n")
    (src / "agent/.gitignore").write_text("data/\nlogs/\n")


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
    (home / "agent/MEMORY.md").write_text(f"# memory template {version}\n")
    (home / "agent/.gitignore").write_text("data/\nlogs/\n")
    return home


BOX_ENV = lambda origin: {"VESTA_UPSTREAM_REF": BRANCH, "AGENT_NAME": "testbox", "VESTA_UPSTREAM_URL": str(origin)}


def _attach(home, origin):
    return _run(ATTACH, home, extra_env=BOX_ENV(origin))
```

(Reuse `_git`, `_run`, `_env`, `BASE_ENV` shapes from the current file — `_run` invokes `bash <script>` with cwd=home.)

Test cases (complete, all must be present):

```python
def test_fresh_attach_is_clean_and_never_touches_worktree(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    marker = home / "agent/skills/tasks/SKILL.md"
    before = marker.read_text()
    r = _attach(home, origin)
    assert r.returncode == 0, r.stdout + r.stderr
    assert marker.read_text() == before
    assert _git(["status", "--porcelain"], home, BOX_ENV(origin)) == ""
    assert not (home / "agent/skills/whatsapp").exists()  # not installed -> off disk


def test_attach_is_idempotent(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    assert _attach(home, origin).returncode == 0
    assert _git(["status", "--porcelain"], home, BOX_ENV(origin)) == ""


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
    env = BOX_ENV(origin)
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    # simulate the upgrade: core mount now runs 0.1.171
    (home / "agent/core/pyproject.toml").write_text('[project]\nname = "vesta"\nversion = "0.1.171"\n')
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
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
    env = BOX_ENV(origin)
    (home / "agent/skills/tasks/SKILL.md").write_text("mine\n")  # conflicts with 0.1.171's edit
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "checkpoint"], home, env)
    _git(["fetch", "origin"], home, env)
    r = subprocess.run(["git", "rebase", "agent-v0.1.171"], cwd=str(home), env=_env(home, env), capture_output=True, text=True)
    assert r.returncode != 0  # conflict markers on disk now
    (home / "agent/skills/tasks/SKILL.md").write_text("both sides survive\n")
    _git(["add", "agent/skills/tasks/SKILL.md"], home, env)
    _git(["rebase", "--continue"], home, env, extra_env_git_editor=True)  # see note below
    assert "both sides survive" in (home / "agent/skills/tasks/SKILL.md").read_text()


def test_install_is_offline_and_remove_drops_dir(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    shutil.rmtree(origin)  # sever the "network": install must still work from local history
    r = _run(SKILLS_INSTALL, home, args=("whatsapp",), extra_env=BOX_ENV(origin))
    assert r.returncode == 0, r.stdout + r.stderr
    assert (home / "agent/skills/whatsapp/SKILL.md").exists()
    r = _run(SKILLS_REMOVE, home, args=("whatsapp",), extra_env=BOX_ENV(origin))
    assert r.returncode == 0
    assert not (home / "agent/skills/whatsapp").exists()


def test_install_unknown_skill_errors_and_reverts_cone(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    cone_before = _git(["sparse-checkout", "list"], home, BOX_ENV(origin))
    r = _run(SKILLS_INSTALL, home, args=("nope",), extra_env=BOX_ENV(origin))
    assert r.returncode == 1
    assert _git(["sparse-checkout", "list"], home, BOX_ENV(origin)) == cone_before


def test_managed_cone_never_materializes_or_stages_core(tmp_path):
    origin, _ = _publish_fixture(tmp_path)
    home = _fresh_box(tmp_path, origin)
    assert _attach(home, origin).returncode == 0
    env = BOX_ENV(origin)
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
    env = BOX_ENV(origin)
    _git(["sparse-checkout", "add", "agent/core"], home, env)
    _git(["fetch", "origin"], home, env)
    _git(["rebase", "agent-v0.1.171"], home, env)
    assert "0.1.171" in (home / "agent/core/loops.py").read_text()
    assert "0.1.171" in (home / "agent/core/pyproject.toml").read_text()


def test_downgrade_transplants_delta_onto_older_snapshot(tmp_path):
    origin, _ = _publish_fixture(tmp_path, versions=("0.1.170", "0.1.171"))
    home = _fresh_box(tmp_path, origin, version="0.1.171")
    assert _attach(home, origin).returncode == 0
    env = BOX_ENV(origin)
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
    env = BOX_ENV(origin)
    # Fabricate the legacy shape: a repo with old no-cone patterns and stray engine files.
    _git(["init", "-b", "testbox"], home, env)
    (home / ".git/info").mkdir(parents=True, exist_ok=True)
    (home / ".git/info/sparse-checkout").write_text("/agent/\n!/agent/core/\n!/agent/skills/*/\n")
    (home / "agent/pyproject.toml").write_text("stale\n")
    (home / "agent/MEMORY.md").write_text("# memory template 0.1.170\nmy personal notes\n")
    assert _attach(home, origin).returncode == 4
    # Documented migration spine:
    (home / ".git").rename(home / ".git-legacy")
    (home / "agent/pyproject.toml").unlink()
    assert _attach(home, origin).returncode == 0
    status = _git(["status", "--porcelain"], home, env)
    assert "agent/MEMORY.md" in status  # personalization surfaced, not lost
    _git(["add", "-A"], home, env)
    _git(["commit", "-m", "migrated: local customizations"], home, env)
    assert "my personal notes" in (home / "agent/MEMORY.md").read_text()
```

Note on `rebase --continue` in tests: git opens an editor; pass `GIT_EDITOR=true` via the env helper (add it to `BASE_ENV`). Drop the fake kwarg in the sketch above and just include `"GIT_EDITOR": "true"` in `BASE_ENV`.

- [ ] **Step 2: Update test_deployment.py**

Remove `"upstream-sync"` from `expected_skills` (the `agent/skills/` list) and add:
```python
    core_skills_dir = source_root / "core" / "skills"
    for skill_name in ("app-chat", "upstream-sync"):
        assert (core_skills_dir / skill_name).is_dir(), f"Core skill '{skill_name}' missing"
```
Check `test_default_skills.py` and the index test for `upstream-sync` references; the index test should still pass because `generate-index.py` indexes `core/skills/` (upstream-sync stays in `index.json`).

- [ ] **Step 3: Run the suite, iterate**

Run: `cd agent && uv run --project core pytest tests/test_upstream_sync.py tests/test_publish_agent_branch.py tests/test_deployment.py -v`
Expected: PASS. The likely rough edges: sparse-checkout `--stdin` path formats (cone mode wants no trailing slash — normalize in attach.sh with `sed 's|/$||'` if needed), `git reset --mixed` on unborn HEAD ordering, `status --porcelain` output for out-of-cone dirs. Fix the scripts, not the assertions — the assertions are the spec's guarantees.

- [ ] **Step 4: Full agent suite**

Run: `./check.sh agent`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agent/tests/
git commit -m "test(agent): pin the agent-branch box flow with real-git scenarios"
```

---

### Task 10: Reference sweep — dream, birth, docstrings, migration retirement, CLAUDE.md

**Files:**
- Modify: `agent/skills/dream/SKILL.md` (§5 Upstream, ~line 82-88)
- Modify: `agent/skills/birth/SKILL.md` (~line 18)
- Modify: `agent/core/default_skills.py` (module docstring, ~line 4-5)
- Delete: `agent/core/migrations/2026-06-workspace-resync.md`
- Modify: `CLAUDE.md` (Skills section, LLM-provider invariant paragraph, Session persistence — anything describing the old sync)
- Regenerate: `agent/skills/index.json` (dream description unchanged → likely no-op; run anyway)

- [ ] **Step 1: dream/SKILL.md §5**

Replace the first paragraph of `### 5. Upstream`:
> Read `upstream-sync` then `upstream-pr` and follow them in order. Either can be a no-op; don't invent work to fill them. Note in the summary what was synced or filed (or that both were no-ops, and why).

with:
> Read `upstream-pr` and follow it (workspace syncing is no longer a dream task — it happens automatically after upgrades via the upstream-sync core skill). It can be a no-op; don't invent work to fill it. Note in the summary what was filed (or that it was a no-op, and why).

Leave the rest of §5 (the pr.py auth note, queue, completion gate) untouched.

- [ ] **Step 2: birth/SKILL.md**

In the housekeeping sentence (~line 18), delete the clause
> `~/agent/skills/upstream-sync/SETUP.md` to set up your git workspace (do not sync; you are already on the current version, and nightly maintenance pulls upstream later);

so it reads: "Run the housekeeping silently between replies, never making them wait: set up `tasks` and `dashboard` (…); in MEMORY.md replace every `[agent_name]` with your name. …" — no mention of workspace, sync, or upstream anywhere in the file (grep it).

- [ ] **Step 3: default_skills.py docstring**

Update the parenthetical "(not deferred behind the agent's next upstream-sync, which only touches `skills/`)" to "(not deferred behind the agent's next upstream sync)". The reconciler behavior itself is unchanged.

- [ ] **Step 4: Retire the workspace-resync migration**

```bash
git rm agent/core/migrations/2026-06-workspace-resync.md
```
(Superseded: legacy convergence is the sync flow's migration path; a legacy agent with it pending gets the same outcome from the new boot turn. Fresh agents pre-mark regardless; an already-recorded `applied_migrations` entry for it is inert.)

- [ ] **Step 5: CLAUDE.md**

Update the stale architecture claims (surgical, keep style):
- Project Overview "Skills" bullet + `Skills` flow section: skills are installed via the sparse cone of the published agent branch (`skills-install` = `git sparse-checkout add`); `index.json` note unchanged.
- The **LLM provider** section's `.claude` invariant paragraph: note the enforcement is now legacy-only (published branch never tracks `.claude`; entrypoint guard is LEGACY until fleet convergence).
- Add to Key Flows a short **Upstream sync** paragraph: version-pinned rebase onto `agent-vX.Y.Z` snapshots published to `agent-workspace` on release; upgrade boot turn + `mark_upstream_synced`; managed vs unmanaged = `agent/core` in the checkout cone or not; engine (= `agent/core/`, incl. its pyproject/uv.lock) is one read-only mount.
- Commands section: note agent tooling runs via `uv run --project core` (check.sh unchanged as entry point).

- [ ] **Step 6: Regenerate index, run everything**

```bash
uv run python agent/skills/generate-index.py
./check.sh agent && ./check.sh vestad && ./check.sh cli
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs: retire nightly sync references; document agent-branch distribution"
```

---

### Task 11: Final verification + PR

- [ ] **Step 1: Full local gate**

```bash
./check.sh all
git log --oneline master..HEAD
rg -n 'LEGACY\(' vestad/src agent/  # exactly the two markers from Task 2
rg -n 'upstream-sync' agent/ CLAUDE.md --glob '!agent/core/skills/upstream-sync/**' --glob '!*.lock' --glob '!agent/skills/index.json'
```
Expected: `check.sh all` green; the `upstream-sync` grep shows only intentional references (dream §5 note, tests, default_skills docstring's absence, CLAUDE.md's new paragraph, skills-install's attach path).

- [ ] **Step 2: Manual repo setting (flag to the user):** add a branch-protection rule for `agent-workspace` so only the workflow (GITHUB_TOKEN / admins) can push and force-pushes are blocked. Not automatable from this checkout — list it in the PR body as a pre-merge checklist item.

- [ ] **Step 3: Ask the user before opening the PR** (per their explicit-approval preference). PR body summarizes the four parts and links the spec; one PR per their call, with the seam note from the spec.

## Self-Review Notes

- Spec coverage: Part 1 → Tasks 4-5; Part 2 → Task 8; Part 3 → Tasks 1-3; Part 4 publish → Tasks 6-7; Part 4 box flow + migration → Tasks 8-9; reference updates → Task 10; testing section → Tasks 2, 6, 9.
- Known intentional deviations: sync.sh is not kept as a script (SKILL.md documents raw porcelain; attach.sh/status.sh are the only scripts) — matches the spec's "at most a tiny helper script". Publish-script tests live in the agent pytest suite for harness reuse.
- Transient red between Tasks 8 and 9 (old tests reference deleted scripts) — execute back-to-back.
