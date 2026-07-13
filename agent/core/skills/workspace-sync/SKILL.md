---
name: workspace-sync
description: Renamed to upstream-sync. Read ~/agent/core/skills/upstream-sync/SKILL.md instead.
---

# Workspace Sync (renamed to upstream-sync)

LEGACY(remove-when: no agent predating the release that ships this rename remains and
the 2026-07 workspace migrations are fleet-applied): released migration prompts and
old boxes' synced scripts reference these paths verbatim. Everything this skill
documented, including the Sync section the 2026-07 migrations point at, now lives in
`~/agent/core/skills/upstream-sync/SKILL.md`; read that file and follow it as written.
The scripts under `scripts/` forward to their renamed counterparts.
