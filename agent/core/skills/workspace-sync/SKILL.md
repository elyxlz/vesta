---
name: workspace-sync
description: Bring your home files up to date after a Vesta upgrade, rebasing your own changes onto the new version's stock files. Use when the upgrade boot turn or the user asks for a workspace sync.
---

# Workspace Sync

Your home is a git repository. Its `origin` carries the stock agent files for every
Vesta version: one commit per release, tagged `agent-vX.Y.Z`, on the branch named by
`$VESTA_WORKSPACE_REF`. When Vesta upgrades, the core you run updates by itself (it is
a read-only mount), but the rest of your home (skills, MEMORY.md, prompts) stays as it
was. Syncing closes that gap: rebase onto the tag matching the version you now run, so
you take every stock update and everything you changed or added yourself stays on top.
To contribute changes back to the Vesta project, see `~/agent/skills/upstream-pr/SKILL.md`.

The version you are running: `grep '^version = ' ~/agent/core/pyproject.toml`

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
- For `agent/MEMORY.md`, keep your accumulated knowledge and adopt the stock structure.
- Then call `mark_workspace_synced`. If the rebase brought changes, call `restart_vesta`
  (after marking) so updated skills load.

## Status

`~/agent/core/skills/workspace-sync/scripts/status.sh` shows what you have changed since
your current version's tag, and the newest published release. Read-only.

## Updating core yourself (boxes created with --no-manage-core-code)

If your core is not a read-only mount, it is part of your checkout and updates only
when the user asks:

```bash
git sparse-checkout add agent/core        # once, ever
git fetch origin
git rebase agent-vX.Y.Z                   # target release: core + skills move together
```

Restart afterwards. Moving to an OLDER release transplants your changes instead:
`git rebase --onto agent-vOLD agent-vCURRENT`.

## Tidy-up (occasionally, e.g. during a dream)

Collapse your accumulated checkpoint commits into one readable commit:

```bash
git reset --soft agent-vX.Y.Z             # your current base tag; files untouched
git commit -m "my customizations"
```
