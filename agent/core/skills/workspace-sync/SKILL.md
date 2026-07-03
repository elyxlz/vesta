---
name: workspace-sync
description: Sync your workspace with the published agent branch after an upgrade.
---

# Workspace Sync

Your home is a git checkout of the published agent branch (`$VESTA_WORKSPACE_REF`). Each
release publishes one snapshot commit tagged `agent-vX.Y.Z`. You sync by rebasing your
local changes onto the snapshot matching the core version you are running, so your
changes always stay on top. To contribute changes back, see
`~/agent/skills/upstream-pr/SKILL.md`.

Your running version: `grep '^version = ' ~/agent/core/pyproject.toml`

## Sync (after an upgrade, when the boot turn asks)

First check the workspace exists: if `~/.git` is missing, run
`~/agent/core/skills/workspace-sync/scripts/attach.sh` (idempotent; exit 4 means a legacy
pre-branch workspace, converted by the one-time workspace boot migration). Then:

```bash
cd ~
git add -A && git commit -m checkpoint    # only if `git status` shows changes
git fetch origin
git rebase agent-vX.Y.Z                   # the version from the boot turn
```

- Conflicts: edit each conflicted file so both sides survive, `git add <file>`, then
  `git rebase --continue`. `git rebase --abort` restores exactly the pre-sync state.
- For `agent/MEMORY.md`, keep your accumulated knowledge and adopt upstream's structure.
- Then call `mark_workspace_synced`. If the rebase brought changes, call `restart_vesta`
  (after marking) so updated skills load.

## Status

`~/agent/core/skills/workspace-sync/scripts/status.sh` shows your delta vs your
snapshot, and the branch tip. Read-only.

## Core updates on unmanaged boxes (created with --no-manage-core-code)

On these boxes vestad does not mount core; it is part of your checkout and updates
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
