---
name: workspace-sync
description: Sync your workspace after a Vesta upgrade, rebasing your own changes onto the new version's stock workspace. Use during the upgrade boot turn or when the user asks to sync.
---

# Workspace Sync

Your workspace (`~`) is a git repository. Vesta's daemon serves its stock contents for the
version you run: one commit per release, tagged `agent-vX.Y.Z`, fetched as a bundle over
the local machine (no internet involved). When Vesta upgrades, the core you run changes with
it (it is a read-only mount), but the rest of your workspace (skills, MEMORY.md,
prompts, etc) stays as it was. Syncing closes that gap: rebase onto the tag matching the version
you now run, so you take every stock change while everything you changed or added yourself
stays on top. To contribute changes back to the Vesta project, see
`~/agent/skills/upstream-pr/SKILL.md`.

The version you are running: `grep '^version = ' ~/agent/core/pyproject.toml`

## Sync (after an upgrade, when the boot turn asks)

```bash
cd ~
git add -A && git commit -m checkpoint    # only if `git status` shows changes
bash ~/agent/core/skills/workspace-sync/scripts/fetch-workspace.sh
git rebase agent-vX.Y.Z                   # X.Y.Z = the version you are running (see top)
```

- Conflicts: edit each conflicted file so both sides survive, `git add <file>`, then
  `git rebase --continue`. `git rebase --abort` restores exactly the pre-sync state.
- Paused but `git diff --diff-filter=U` lists no files? Not a conflict: the rebase stopped
  on a commit that's now empty (its changes are already in the new stock) or mode-only.
  Run `git add -A` then `git rebase --continue`; if git says the commit is empty, run
  `git rebase --skip`. Don't hunt for conflict markers that aren't there.
- For `agent/MEMORY.md`, keep your accumulated knowledge and adopt the stock structure.
- Then call `mark_workspace_synced`. If the rebase brought changes, call `restart_vesta`
  (after marking) so the new skills load.

## Status

`~/agent/core/skills/workspace-sync/scripts/status.sh` shows what you have changed since
your current version's snapshot, and the newest snapshot Vesta's daemon has. Read-only.

## Tidy-up (occasionally, e.g. during a dream)

Collapse your accumulated checkpoint commits into one readable commit:

```bash
git reset --soft agent-vX.Y.Z             # your current base tag; files untouched
git commit -m "my customizations"
```
