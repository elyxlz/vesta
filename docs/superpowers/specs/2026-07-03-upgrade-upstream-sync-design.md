# Upgrade-driven sync, core-skill tooling, engine consolidation, agent-branch distribution

**Date:** 2026-07-03
**Status:** Parts 1–3 implemented. Part 4's github-branch distribution is superseded by
`2026-07-03-vestad-local-workspace-distribution.md` (the workspace remote ships with vestad;
boxes sync from a local bundle over the loopback, never from github).

## Goal

Developers improve skills, add skills, edit the core, and reshape the agent home layout — all
on `master` as today. A CI job publishes the result to a dedicated **agent branch**: the
complete, ready-to-run content of an agent's home. Fresh agents spawn from it directly.
Working fleets track it with **local changes always on top** (`git pull --rebase`), fixing
conflicts agentically. Managed boxes sync when a vestad upgrade tells them to (boot turn);
unmanaged-core boxes (`--no-manage-core-code`) additionally pull core itself when the user
asks. Box-side git is standard porcelain only — no hand-built sparse patterns, no shallow
tricks, no custom scripts doing git surgery.

One spec, one PR (user's call; seams noted at the end).

## Part 1 — Upgrade detection and boot turn

A vestad upgrade re-extracts the agent core mount, so the running core version (read from the
bind-mounted `pyproject.toml`, release-synced with vestad's version by CI) changes across the
restart. That version is the upgrade signal — agent-side only, no new vestad contract.

- `PersistedState` (`agent/core/state_store.py`) gains `last_synced_version: str | None = None`.
- A new turn builder module (`agent/core/upgrade_sync.py`, mirroring `default_skills.py`)
  compares `last_synced_version` to the running version and returns a boot-turn body on
  mismatch, or `None`.
- `_vesta_version()` moves to a single shared owner (it also gains the new pyproject location,
  Part 3) so `main.py`'s startup log and the turn builder read one implementation.

Rules:

- **First start:** no turn; pre-mark the current version (fresh image is already current —
  the same pattern fresh agents use to pre-mark migrations).
- **Version unreadable ("unknown"):** no turn, no marking. Never churn on a broken pyproject.
- **Mismatch:** emit the turn. Covers legacy agents with no marker (fires once on the upgrade
  that ships this — correct) and downgrades.
- **Unmanaged-core boxes:** their running core only changes when *they* pull it, so the turn
  naturally never fires on a vestad upgrade — their sync is user-instructed, by design.

Ordering in `collect_boot_turns` (`agent/core/main.py`): migrations → **upstream sync** →
default-skill sync → config issues → greeting (sync first so a refreshed registry precedes
any default-skill installs).

### Completion: mark-on-success tool

New `mark_upstream_synced` MCP tool in `agent/core/tools.py`, mirroring
`mark_migration_applied`: records the running version into `persisted.last_synced_version`.
Unmarked (conflict left mid-rebase, network down, crash) → the turn re-fires next boot until
it succeeds; the sync flow is idempotent/resumable.

### Turn body

> [Upstream sync] Vesta was upgraded (now vX.Y.Z). Read
> `~/agent/core/skills/upstream-sync/SKILL.md` and follow it to bring your workspace to this
> version's snapshot (rebase your changes onto `agent-vX.Y.Z`), resolving any conflicts. Then
> call `mark_upstream_synced`. If the rebase brought changes, call `restart_vesta` afterward
> so updated skills load; if it was a no-op, no restart is needed. If it fails, tell the user
> what blocked it.

Marking happens **before** the restart so the restarted boot does not re-fire the turn.

## Part 2 — upstream-sync becomes a core skill

Move `agent/skills/upstream-sync/` → `agent/core/skills/upstream-sync/`. End state, identical
to `app-chat`:

- Ships read-only with the engine; updates with core (on upgrade for managed boxes, on the
  box's own core pull for unmanaged ones), never via the sync it performs — a broken sync
  tool can now always be healed by the next upgrade.
- Not in the installable registry; present on every agent. Indexed/discovered like any core
  skill (`generate-index.py` and the entrypoint symlinks already cover `core/skills/`).
- No setup step: `SETUP.md` deleted; the sync flow self-initializes a virgin workspace
  (attach flow, Part 4). Birth stops mentioning the workspace/sync/upstream entirely.
- Contents shrink to `SKILL.md` (+ at most a tiny helper script): with Part 4 the flow is
  standard git commands an agent already knows. `init.sh`, `narrow-sparse-checkout.sh`, and
  most of `sync.sh` are deleted rather than moved.

`upstream-pr` stays in `agent/skills/` — agent-owned contribution tooling; paths unchanged
(`agent/` prefix preserved on the branch), and the rebase model makes "this box's delta" =
"commits above the last publish", which is exactly what PR filing wants.

## Part 3 — Engine consolidation: pyproject.toml + uv.lock move into core/

The agent Python project is deps-only (no build system; `python -m core.main` resolves via
cwd), so `agent/pyproject.toml` and `agent/uv.lock` move to `agent/core/pyproject.toml` and
`agent/core/uv.lock` **with zero code restructuring**. Launch becomes
`uv run --project core --frozen python -m core.main`.

- **One engine directory.** vestad's three engine mounts collapse to one
  (`/root/agent/core`); `MOUNT_DESTS` drops two entries; `manage_core_code` gates one bind.
  "Vestad-managed paths" collapses from three items to one everywhere (docs, ignores, cone).
- **Fleet migrates itself:** the entrypoint command change is itself a rebuild trigger
  (`needs_rebuild` command mismatch), so **every** container is rebuilt on this upgrade,
  arriving on the single-mount shape in the same pass. No migration to write.
- **Unmanaged boxes keep booting during the transition:** an unmanaged box still has the old
  core layout on disk until it pulls a post-move snapshot, so the entrypoint launch step
  tolerates both layouts (`core/pyproject.toml` present → `--project core`, else the legacy
  launch), marked `LEGACY(remove-when: unmanaged boxes have pulled a post-move snapshot)`.
  Without this they crash-loop with no agent alive to self-heal.
- **The venv lives outside the read-only mount:** the container pins
  `UV_PROJECT_ENVIRONMENT` to a writable path (`~/agent/.venv`) — uv's default would be
  `core/.venv`, inside the managed read-only mount.
- **Both mount shapes stay recognizable:** `mounts_have_core_code` (which restore/rebuild use
  to re-derive `manage_core_code` from an existing container) accepts the legacy three-mount
  and the new single-mount shape — restoring a pre-move restic backup must not silently flip
  a box to unmanaged.
- `agent_embed.rs` drops its explicit `pyproject.toml`/`uv.lock` include lines (the existing
  `core/**/*` glob covers them post-move); `build.rs` embed-hash inputs get the same path
  check.
- Mechanical plumbing, same PR: entrypoint cmd (`docker.rs`), Dockerfile copy/sync steps,
  `check.sh` agent suite (`--project core` + config flags for ruff/ty/pytest whose relative
  paths anchor to the pyproject location), CI version-sync paths, `release.sh` bump paths,
  dependabot directory, `_vesta_version()` path. All failures are loud (`check.sh`/CI).

This move is what makes Part 4's checkout model work: with no loose engine files at the
`agent/` level, directory-granular (cone-mode) sparse checkout expresses managed vs unmanaged
as a single directory entry — no symlinks, no pattern files.

## Part 4 — Agent-branch distribution

### The published branch

A CI job publishes the **complete agent home** to a dedicated branch (working name:
`agent-workspace`; `VESTA_UPSTREAM_REF` names it, one owner):

- **Content:** `agent/core/` (engine: code, skills, prompts, pyproject, uv.lock),
  `agent/skills/` (all registry skills), `agent/MEMORY.md`, `agent/.gitignore`, and a
  workflow-owned **root `.gitignore`** (`/*`, `!/agent/`, plus the bulky-file globs that
  today are hand-appended to `info/exclude`). `~/.claude` is never tracked — the
  credentials-deletion hazard is structurally gone.
- **Publish = construct, never rewrite.** The job checks out the branch, rsyncs the filtered
  tree from the release tag, commits if changed (`publish vX.Y.Z from <sha>`), **tags the
  commit `agent-vX.Y.Z`**, and pushes branch + tag with `git push --atomic` (both refs update
  or neither). Append-only by construction; a guard refuses non-fast-forward pushes;
  bootstraps an orphan first commit if the branch is absent. Branch-protect it so only the
  workflow can push.
- **Never out of sync, by construction (not by pipeline timing).** Boxes do not chase the
  branch tip: every sync rebases onto the snapshot tagged with the box's **own running core
  version** (see box-side model). Skills and core therefore match regardless of when the
  branch push lands relative to the rest of the release. A missing snapshot makes sync fail
  loudly, and the mark-on-success loop re-fires it every boot until the snapshot exists —
  visible and self-retrying, never silent drift.
- **Cadence and ordering: on release**, inside the gated pipeline: test-live gate → publish
  branch + tag → artifacts and the `:latest` image, gated on the branch push succeeding. Both
  partial-failure directions are then harmless: branch-pushed-but-release-failed leaves an
  inert snapshot no box targets (no box ever runs that core version); artifacts-without-branch
  is structurally unreachable. Publish logic lives in a tested script, not inline YAML.

### `VESTA_UPSTREAM_REF` semantics (docker.rs `detect_upstream_ref`)

Today it yields the release tag `vX.Y.Z` (release builds) or vestad's current git branch (dev
builds). It becomes **the box's fetch target — the agent branch name**: release builds return
`agent-workspace`; the box derives its snapshot tag (`agent-v<version>`) itself from the core
version it runs (Part 1 owns that read). Dev builds return the dev's own agent branch: the
publish script is a standalone tested tool a developer runs manually to publish
`agent-workspace-<branch>` from their checkout when exercising the sync flow itself —
day-to-day core hacking needs no branch at all (dev vestad re-embeds and re-mounts core
without git).

### Box-side model (standard porcelain only)

- **Attach once (idempotent, self-init):** `git init` + `remote add` with the fetch refspec
  pinned to exactly `$VESTA_UPSTREAM_REF` + `agent-v*` tags (never the monorepo's branches or
  release tags, which would drag master history onto the box), cone-mode sparse checkout, box
  branch `$AGENT_NAME` created on its version's snapshot. Fresh boxes' on-disk content equals
  that snapshot, so the attach never rewrites the working tree. No shallow, no partial clone —
  branch history is one commit per release.
- **Cone = what this box tracks**, all managed by `git sparse-checkout` porcelain:
  - Managed box: the installed skill dirs (`agent/skills/<name>`). `agent/core` is never
    listed → engine stays off disk; the read-only mount provides it.
  - Unmanaged box: the same **plus `agent/core`** — engine updates arrive through the very
    same pull, user-triggered. Local core modifications ride on top like any other local
    change (a coherent self-modifying-agent story, not a special case).
  - Cone-mode ancestor rules materialize `agent/MEMORY.md`, the `.gitignore`s, and
    `agent/skills/index.json` automatically — exactly the wanted loose files, which is why
    Part 3 had to clear the engine files out of `agent/`.
- **Sync = rebase onto your version's snapshot, local changes always on top:**
  `git add -A && git commit -m checkpoint` (if dirty), then fetch and
  `git rebase agent-v<running core version>` — not the branch tip. Conflicts are plain
  conflict markers fixed agentically, `git rebase --continue`. Managed boxes are moved to a
  new snapshot by the upgrade boot turn; an unmanaged box moves core + skills **together** by
  rebasing onto whichever release's snapshot the user chooses (downgrades work the same way —
  rebasing onto an older snapshot is the identical operation). The skill advises periodically
  squashing the box's delta into a rolling "customizations" commit so each sync re-applies
  one clean patch and the box's whole personality is readable as a single diff.
- **Install a skill = `git sparse-checkout add agent/skills/<name>`** + restart. No network
  (single-branch history is local), no pattern files, instant. Uninstall =
  porcelain removal from the cone. "Installed = on disk" is preserved, so the default-skill
  reconciler and the entrypoint symlink loop are **untouched**; `skills-install` shrinks to
  the one command (kept as the stable entry point the reconciler and docs name).

### Fleet migration (one-shot, prompt-guided)

Legacy workspaces (no-cone sparse patterns, shallow master-based history) are converted by
the first upgrade boot turn, guided by the skill, not by script archaeology: tarball
`~/agent` as a safety net → record the skills currently on disk → detach the old repo state →
attach fresh to the branch (cone seeded from that skill list) → restore local
personalizations from the backup where files differ (the agent judges, resolving like any
conflict) → delete stale loose engine files left by the mount consolidation
(`~/agent/pyproject.toml`, `~/agent/uv.lock` — rebuilds preserve the container filesystem, so
they linger as dead regular files) → checkpoint commit → `mark_upstream_synced`. Idempotent: a
converted box no longer
matches the legacy shape, so re-runs are the normal pull flow. The attach flow doubles as the
recovery path if the branch ever has to be replaced (merge base gone → re-attach).

- The entrypoint's `.claude` untrack/exclude guard becomes
  `LEGACY(remove-when: fleet converged to agent-branch workspaces)`.
- `agent/core/migrations/2026-06-workspace-resync.md` is retired — superseded by this flow.

### Reference updates (same PR)

- `agent/skills/dream/SKILL.md` §5: `upstream-pr` only; one-line note that syncing happens
  after upgrades.
- `agent/skills/birth/SKILL.md`: workspace-setup clause removed entirely.
- `agent/core/skills/upstream-sync/SKILL.md`: rewritten for the branch/rebase flow
  (yours-vs-vestad's collapses to "core is the engine; on managed boxes it's not even in
  your checkout").
- `agent/skills/skills-registry/`: `skills-install` becomes the one-liner.
- `agent/core/default_skills.py`: docstring's stale "nightly upstream-sync" reference.
- Regenerate `agent/skills/index.json`.

## Out of scope

- `upstream-pr` mechanics (verify against the new shape; expected no-op).
- Deriving the agent Docker image itself from the published branch (attractive long-term
  convergence — the branch already *is* the home content — but a separate initiative).
- Any change to the `manage_core_code` flag surface (it exists and suffices).

## Testing (same PR)

- Part 1: turn builder mismatch/match/first-start/unknown matrix; pre-marking;
  `mark_upstream_synced` persistence; `collect_boot_turns` ordering (`test_boot_turns.py`).
- Part 3: `check.sh agent` green under the new layout (that suite *is* the test);
  vestad mount tests updated (single engine mount, `mounts_have_core_code`,
  `needs_rebuild` drift on legacy three-mount containers); entrypoint assertions cover the
  dual-layout launch shim and the `UV_PROJECT_ENVIRONMENT` pin.
- Part 4 publish: script exercised against a scratch repo — one commit per changed release,
  no-op when unchanged, bootstraps absent branch, refuses non-fast-forward, branch + `agent-v*`
  tag pushed atomically.
- Part 4 box flow (`test_upstream_sync.py` rewritten, real git repos as today): fresh attach;
  checkpoint + version-pinned rebase with/without conflicts; rebase onto an older snapshot
  (downgrade); missing snapshot fails loudly and leaves the workspace intact; cone add/remove
  for install/uninstall;
  managed cone never materializes `agent/core` (and `git add -A` never stages mount content);
  unmanaged cone pulls core updates; legacy-workspace conversion preserves local edits and
  seeds the cone from on-disk skills; attach/conversion idempotency.
- `./check.sh agent`, `./check.sh cli`, `./check.sh vestad`, index freshness, CI green.

## PR note

One PR by explicit user preference. If review size becomes a problem, the natural seams are:
(1) Part 3 engine consolidation (mechanical, independently green), (2) Part 4's publish job
(inert until boxes point at the branch), (3) the box-side flow + Parts 1–2. Not the plan of
record.
