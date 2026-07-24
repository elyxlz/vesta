---
name: upstream-sync
description: Sync your workspace after a Vesta upgrade, rebasing your own changes onto the new version's stock snapshot. Use during the upgrade boot turn, or when the user asks you to get up to date or get the latest changes.
---

# Upstream Sync

Your workspace (`~`) is a git repository: a plain full checkout of Vesta's stock content
(your skills and `MEMORY.md`). Vesta's daemon keeps that stock in a per-host snapshot repo,
bind-mounted read-only at `/run/vesta-upstream`: one commit per release, tagged `agent-vX.Y.Z`,
fetched locally (no internet involved). When Vesta upgrades, the core you run changes with it
(it is a read-only mount), and syncing brings the rest of your workspace up to the same
version: rebase onto the tag matching the version you now run, so you take every stock change
while everything you changed or added yourself stays on top. To contribute changes back to the
Vesta project, see `~/agent/skills/upstream-pr/SKILL.md`.

The version you are running: `grep '^version = ' ~/agent/core/pyproject.toml`

## Sync (after an upgrade, when the boot turn asks)

```bash
bash ~/agent/core/skills/upstream-sync/scripts/sync.sh
```

The whole procedure, idempotent. Run it, never the porcelain by hand. Exit 5 means it stopped
on a conflict, which is yours:

- Conflicts: ALWAYS resolve by hand, and the default is to keep BOTH sides, your change
  AND the stock change, not pick a winner. Do NOT reflexively `git checkout --ours/--theirs`
  or blanket-take one side: that silently drops real work. Even a file you upstreamed comes
  back genericized, so take stock's form and re-apply your local specifics on top rather
  than discarding either. Edit each conflicted file so both sides survive, `git add <file>`,
  then `git rebase --continue` and re-run sync.sh to finish. `git rebase --abort` restores
  exactly the pre-sync state.
- Paused but `git diff --diff-filter=U` lists no files? Not a conflict: the rebase stopped
  on a commit that's now empty (its changes are already in the new stock) or mode-only.
  Run `git add -A` then `git rebase --continue`; if git says the commit is empty, run
  `git rebase --skip`. Don't hunt for conflict markers that aren't there.
- For `agent/MEMORY.md`, keep your accumulated knowledge and adopt the stock structure.
- Then call `mark_upstream_synced`. If the rebase brought changes, call `restart_vesta`
  (after marking) so the new skills load.

## Status

`~/agent/core/skills/upstream-sync/scripts/status.sh` shows what you have changed since
your current version's snapshot, and the newest snapshot Vesta's daemon has. Read-only.

## Tidy-up (occasionally, e.g. during a dream)

Collapse your accumulated checkpoint commits into one readable commit:

```bash
git reset --soft agent-vX.Y.Z             # your current base tag; files untouched
git commit -m "my customizations"
```
