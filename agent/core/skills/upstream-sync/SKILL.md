---
name: upstream-sync
description: Sync your workspace with the published agent branch after an upgrade; install core updates on unmanaged boxes; resolve rebase conflicts; one-time legacy migration.
---

# Upstream Sync

Your home is a git checkout of the published agent branch (`$VESTA_UPSTREAM_REF`). Each
release publishes one snapshot commit tagged `agent-vX.Y.Z`. You sync by rebasing your
local changes onto the snapshot matching the core version you are running, so your
changes always stay on top. To contribute changes back, see
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

`~/agent/core/skills/upstream-sync/scripts/status.sh` shows your delta vs your
snapshot, and the branch tip. Read-only.

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
tar czf ~/agent-backup.tar.gz agent       # safety net, keep until verified
ls ~/agent/skills > /tmp/installed-skills # what installed means today
mv ~/.git ~/.git-legacy                   # retire the old repo (delete on a later dream)
~/agent/core/skills/upstream-sync/scripts/attach.sh
git status                                # your personalizations vs stock; judge each:
                                          # keep yours, take stock, or integrate both
rm -f ~/agent/pyproject.toml ~/agent/uv.lock   # stale leftovers of the engine move
git add -A && git commit -m "migrated: local customizations"
```

Then `mark_upstream_synced` and restart. Re-running any of this is safe: attach.sh is
idempotent and a converted workspace no longer matches the legacy shape.
