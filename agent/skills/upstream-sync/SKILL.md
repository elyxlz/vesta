---
name: upstream-sync
description: Sync local agent code with upstream vesta: updates, merges, conflicts.
---

# Upstream Sync

Keep your branch current with upstream. To push contributions out, see [upstream-pr](../upstream-pr/SKILL.md).

Two scripts do the work. You rarely need raw git here.

- **See where you stand:** `~/agent/skills/upstream-sync/scripts/status.sh`
  Read-only. Shows how far behind/ahead of `$VESTA_UPSTREAM_REF` you are, the upstream commits you haven't integrated, your own changes vs upstream, and anything uncommitted.

- **Pull upstream in:** `~/agent/skills/upstream-sync/scripts/sync.sh`
  Does the whole mechanical spine deterministically: checkpoint local work, narrow the sparse cone, fetch, then either merge (shared history) or re-anchor (no shared history, e.g. the repo was recreated), then force `skills/index.json` to the upstream registry and re-apply `skip-worktree` on bind-mounted paths.

  `index.json` is always the full upstream registry of available skills (so `skills-install` can pull any of them), even though only installed skills are on disk. `sync.sh` keeps it that way, never shrinks it to what's checked out.

## Resolving conflicts

`sync.sh` only stops for one reason: a real content conflict during a merge. It exits with code 2 and lists the conflicted files. Resolve each, then run `sync.sh` again, it finalises the merge and finishes the rest.

Resolve as integration work, not `ours` vs `theirs`:
- Default goal is to preserve both behaviours. Rewrite the file so both changes coexist; for bigger collisions, extract helpers or rename.
- `agent/MEMORY.md`: keep your accumulated knowledge, adopt upstream's structure and any new rules where it changed.
- Vestad-managed paths (`agent/core/`, `pyproject.toml`, `uv.lock`) are not automatic `--theirs`; carry local behaviour forward if it matters.
- Take one side wholesale only when the other is obsolete, redundant, generated, or a strict subset.
- Don't stop at "markers removed", re-read the file and confirm both sides survive. Then `git -C ~ add <file>` and re-run `sync.sh`.

## Ownership

`~` is the repo root. Sparse checkout limits the worktree to `agent/` (minus the bind-mounted paths and uninstalled skills) plus root `.gitignore`. Skill directories under `agent/skills/*/` are opt-in: only installed skills are on disk and in `git status`. `agent/skills/index.json` is always visible, it's the registry of available skills regardless of what's installed. Repo-root `.claude/` stays local and untracked. Bulky/local-only stuff goes in `~/agent/.gitignore`.

You own `agent/skills/`, `agent/prompts/`, `agent/MEMORY.md`, `agent/.gitignore`, and `.claude/`. `agent/core/`, `agent/pyproject.toml`, `agent/uv.lock` are bind-mounted read-only by vestad and tracked from upstream, never commit local edits to them.

## Branch model

Your branch (`$AGENT_NAME`) tracks `$VESTA_UPSTREAM_REF`. All local work commits here; sync layers upstream on top.

```
upstream ref
  * local commits
  * sync (merge or re-anchor)
  * more local commits
  * sync
```

If `status.sh` reports no shared history, that's expected after an upstream repo recreation; `sync.sh` re-anchors onto upstream and replays your owned files (`MEMORY.md`, installed skills, `.gitignore`) on top, so you still pull in all upstream content without a wall of false conflicts.

## First-time setup

If the workspace has never been initialised (no git repo, or a stale broad sparse pattern), follow [SETUP.md](SETUP.md) once, then use `sync.sh` from then on.

## Manual escape hatches

The deterministic pieces `sync.sh` calls, if you ever need one directly:
- `scripts/narrow-sparse-checkout.sh` makes `agent/skills/*/` opt-in (only installed skills on disk). Idempotent.
- `scripts/reanchor.sh` re-bases your branch onto upstream when there's no common ancestor.
- `~/agent/skills/skills-registry/scripts/skills-install <name>` adds one registry skill to the worktree.
