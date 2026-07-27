---
name: workspace-sync
description: A pointer to upstream-sync. Read ~/agent/core/skills/upstream-sync/SKILL.md and follow that instead.
---

# Workspace Sync (pointer to upstream-sync)

LEGACY(remove-when: no agent predating the release that ships upstream-sync remains and
the 2026-07 workspace migrations are fleet-applied): released migration prompts and
old boxes' synced scripts reference these paths verbatim. Everything under this name,
including the Sync section the 2026-07 migrations point at, lives in
`~/agent/core/skills/upstream-sync/SKILL.md`; read that file and follow it as written.
Where a migration parenthetically summarizes the sync as a rebase, ignore that summary:
the upstream-sync Sync section is authoritative and uses a merge. The migration may also
call `set-cone.sh` and `mark_workspace_synced` afterward; those compatibility steps are
safe no-ops that verify the result. The remaining scripts under `scripts/` forward to
their upstream-sync counterparts.
