Your voice now auto-loads from core. `build_client_options` reads the `personality` skill's shared `SKILL.md` plus your active preset and injects them into your system prompt on every boot, the same way MEMORY.md is always present. So the old voice-loading line in the restart skill is redundant. Safe to run more than once: it no-ops if there is nothing to remove.

### 1. Drop the obsolete voice-loading line

Open `~/agent/skills/restart/SKILL.md`. If it has a line starting with `Adopt the voice:`, delete that whole line (and any now-empty surrounding blank line). If there is no such line, do nothing. Core loads your voice regardless; nothing replaces this line.

### 2. Mark this migration applied

Call `mark_migration_applied` with `name="2026-06-personality-autoload"`.
