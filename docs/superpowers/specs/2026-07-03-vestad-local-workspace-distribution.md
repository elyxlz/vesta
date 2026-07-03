# Vestad-local workspace distribution: the workspace remote ships with vestad

**Date:** 2026-07-03
**Status:** Draft — pending user approval
**Supersedes:** the "Part 4 — Agent-branch distribution" half of
`2026-07-03-upgrade-upstream-sync-design.md`. Parts 1–3 of that spec (upgrade boot turn +
`mark_workspace_synced`, workspace-sync as a core skill, engine consolidation into
`agent/core/`) are already implemented on `feat/agent-branch-distribution` and carry over
unchanged. This spec replaces where the published content lives and how boxes reach it.

## Why the pivot

The github `agent-workspace` branch made the sync flow production-only by construction: the
remote exists only after a release pipeline publishes it, so dev boxes and tests could never
walk the real path — every testing story was a shim simulating production (local git daemons,
`VESTA_UPSTREAM_URL` overrides, a manually published per-dev branch), and test-live had a
bootstrap deadlock (the publish job is gated on test-live, but test-live's upgraded agent
needs the published snapshot). When testability requires simulating prod, the remote is in
the wrong place.

vestad already owns and ships the agent's code (embedded, extracted, mounted). The fix is to
make vestad own the workspace remote too: **each vestad maintains a local workspace repo
built from the agent content it ships, and serves it to its own boxes over the loopback
channel that already exists.** Dev, tests, and production then run the identical flow,
offline, with content that provably matches the running core.

## The design

### Vestad-side: a per-host workspace repo + bundle

- **Full agent home embedded.** `agent_embed.rs` grows from `core/**` + personality presets
  to the complete publishable tree: `agent/core/**`, `agent/skills/**`, `agent/MEMORY.md`,
  `agent/.gitignore` (same allowlist the publish script used; mostly text, a few MB).
  `build.rs`'s embed-hash inputs widen to match, so any skill edit re-fingerprints and
  re-extracts, exactly like core edits today.
- **One tested script owns the whole construction** —
  `vestad/scripts/build-workspace.sh`, the direct descendant of
  `tools/publish-agent-branch.sh` (same filtered-tree/commit-if-changed/tag mechanics, same
  real-git pytest harness), retargeted from "archive a ref, push to github" to "snapshot a
  content dir into a local bare repo, regenerate the bundle". Contract:

  `build-workspace.sh <content-dir> <workspace-dir> <version>`
  - Init `<workspace-dir>/workspace.git` (bare) if absent.
  - Stage `<content-dir>` (the extracted agent tree — already the right allowlist) plus the
    script-owned root `.gitignore`; commit onto branch `agent-workspace` only if the tree
    changed (subject `snapshot vX.Y.Z`; fixed committer identity). Append-only, no-op when
    unchanged, idempotent.
  - Set tag `agent-vX.Y.Z` (force — it moves on dev same-version churn; in release
    operation the version bumps every upgrade, so tags are effectively immutable there).
  - Regenerate `<workspace-dir>/workspace.bundle` (full branch + `agent-v*` tags)
    atomically (tmp + rename). The bundle, not the repo, is what boxes consume.

  The script is embedded into the vestad binary (`include_str!`), written under the config
  dir, and executed at startup after `ensure_agent_code`. The Rust side
  (`vestad/src/workspace.rs`) stays a thin edge: probe git, materialize the script, run it,
  surface its output — no git logic in Rust. Extending the snapshot behavior means editing
  one bash file with its own test suite, not Rust.
- **History is per-host and append-only**: each host's boxes sync against their own host's
  lineage, so `git rebase agent-vX.Y.Z` always has a real merge-base. Cross-host moves
  (backup restored onto a different host) use the transplant form the skill already
  documents: `git rebase --onto agent-vNEW agent-vOLD` — both tags exist in the box's own
  repo history.
- **Host git becomes a runtime requirement for vestad.** Checked at startup with a clear
  error (like the Docker probe). Today git is only invoked on dev builds; this makes it
  unconditional. Vendoring (restic-style) stays available as a later escape hatch; not now.

### Delivery: over the existing agent→vestad loopback

New endpoint `GET /agents/{me}/workspace.bundle` (dual-auth, self-scoped via
`X-Agent-Token` — same contract as `POST /agents/{me}/restart`): serves the bundle file.

Chosen over a bundle-in-the-core-mount because it also serves **unmanaged boxes** (which
have no core mount — their core arrives through this very sync) and adds no mount topology.
The box is on host networking and reaches vestad at `$VESTAD_PORT`; no external network is
ever involved.

Box side, a tiny helper (`fetch-workspace.sh` in the workspace-sync core skill): curl the
bundle to a temp file, `git fetch <bundle> '+refs/heads/agent-workspace:refs/remotes/origin/agent-workspace' '+refs/tags/agent-v*:refs/tags/agent-v*'`,
delete the temp file. `attach.sh` and the SKILL.md sync flow call it where they previously
ran `git fetch origin`. No configured remote URL at all — the "remote" is whatever bundle
this box's vestad hands it.

### What this deletes

- The CI `publish-agent-branch` job, the github `agent-workspace` branch, its `agent-v*`
  tags on the shared repo, the branch-protection requirement, and the append-only push
  guard / tag-conflict-on-failed-release edge.
- `tools/publish-agent-branch.sh` and `agent/tests/test_publish_agent_branch.py` as such —
  both survive **transformed**: the script becomes `vestad/scripts/build-workspace.sh`
  (push/github parts dropped, bundle step added), the test file becomes
  `test_build_workspace.py` exercising the same script vestad executes, in the same
  real-git harness.
- `detect_workspace_ref` and the `VESTA_WORKSPACE_REF` env var: the branch name is a
  constant (`agent-workspace`) inside the bundle; there is no per-dev branch because every
  host serves its own content. Env-file writer stops emitting it and strips the old keys
  (`LEGACY(remove-when: no agent env file carries VESTA_UPSTREAM_REF or VESTA_WORKSPACE_REF)`).
- `VESTA_UPSTREAM_URL` test knob (tests hand attach a bundle path directly).
- The unreachable-remote contingency in the workspace conversion migration shrinks to the
  vestad-down case (loopback can still refuse); the graceful-degradation shape stays but is
  no longer the expected first-release path.

### What carries over unchanged

- Upgrade detection (`workspace_sync.py`, `last_synced_version`, boot turn,
  `mark_workspace_synced`), boot-turn ordering, first-start pre-mark.
- The box porcelain model: attach (idempotent, worktree-safe, cone = installed skills,
  `sparse.expectFilesOutsideOfPatterns`), checkpoint + version-pinned rebase, conflicts
  fixed agentically, `skills-install` = cone add (offline from local history — the bundle
  carries every registry skill), tidy-up squash, managed vs unmanaged = `agent/core` in the
  cone or not.
- The engine layout (`agent/core/pyproject.toml` + `uv.lock`), single core mount,
  dual-layout entrypoint, and all CI path plumbing from Parts 1–3.
- The one-time legacy conversion as a boot migration.

## Why this is now testable everywhere (the point)

- **Unit (pytest, hermetic):** fixtures build a bundle with plain git (or the same filtered
  tree) and drive the real `attach.sh`/`fetch-workspace.sh`/rebase/cone scripts against it.
  Strictly simpler than today's bare-repo-origin fixtures.
- **Unit (vestad):** `workspace.rs` exercised against scratch dirs — append-only lineage,
  fingerprint-gated snapshots, tag placement, bundle regeneration, no-op on unchanged
  content.
- **Integration (Docker):** a real agent container curls the real endpoint from a real
  vestad and attaches — the actual production path, end to end, no synthetic remote.
- **test-live:** works by construction — the candidate vestad serves its own candidate
  content, so the upgraded agent's migration *and* first real sync converge against exactly
  what is being released. The bootstrap deadlock is gone, not worked around.
- **Dev:** `cargo run` vestad serves whatever your checkout embeds. Virgin-box installs and
  sync exercises work with zero setup and no pushes anywhere.

## Out of scope

- Vendoring git into vestad (host git required; revisit only if it bites real users).
- Deriving the agent Docker image from the workspace content (unchanged from prior spec).
- Any change to the `manage_core_code` flag surface.
- `upstream-pr` mechanics (still cuts PRs from `origin/master` of the monorepo via the
  GitHub App; loses the `$VESTA_WORKSPACE_REF` version label — use
  `vesta_version`'s pyproject read instead).

## Testing (same PR)

- `build-workspace.sh` (pytest, real git — `test_build_workspace.py`): snapshot
  append/no-op/tag-move matrix; bundle contains branch + tags and is fetchable; staged tree
  never contains `.claude`, `vestad/`, or dev-tool configs; bundle regeneration is atomic.
  `workspace.rs` keeps only thin-wrapper tests (git probe error, script materialization).
- Endpoint: auth (agent token, self-scoped), 404 before first snapshot, bytes match bundle.
- Box flow (pytest, re-fixtured to bundles): attach clean/idempotent; version-pinned rebase
  with/without conflicts; downgrade/cross-host transplant; cone scoping incl. mount
  invisibility; offline install/remove; legacy conversion spine.
- Integration: real container attach + sync through the endpoint.
- `./check.sh all` green; index freshness.

## PR note

This lands as a revision of `feat/agent-branch-distribution` (PR #965): Parts 1–3 commits
stand; the distribution half is replaced in follow-up commits on the same branch. If review
size becomes a problem, the seam is vestad-side (`workspace.rs` + endpoint, inert until the
skill points at it) vs box-side (skill scripts + fixtures).
