The `personality` skill moved out of `~/agent/core/skills/` (replaced on every `vestad update`) into `~/agent/skills/` (persists, so your drifted voice survives upgrades). The `proactive-check` skill is now a default skill too. This migration installs both at the new location if they are missing and re-points your voice-loading line. Safe to run more than once: each step checks whether you are already in the end state and no-ops if so.

### 1. Install the personality skill at the new location

If `~/agent/skills/personality/SKILL.md` does not exist, install it:

```bash
~/agent/skills/skills-registry/scripts/skills-install personality
```

### 2. Preserve your drifted voice

If your old preset still exists at `~/agent/core/skills/personality/presets/$AGENT_SEED_PERSONALITY.md`, the dreamer may have drifted it. If it exists and differs from the freshly installed `~/agent/skills/personality/presets/$AGENT_SEED_PERSONALITY.md`, copy the old one forward so you keep your voice:

```bash
old=~/agent/core/skills/personality/presets/$AGENT_SEED_PERSONALITY.md
new=~/agent/skills/personality/presets/$AGENT_SEED_PERSONALITY.md
if [ -f "$old" ] && ! cmp -s "$old" "$new"; then cp "$old" "$new"; fi
```

If the old path is already gone (core was replaced before this ran), there is nothing to preserve; the installed preset is your starting point. That is fine.

### 3. Install proactive-check if missing

If `~/agent/skills/proactive-check/SKILL.md` does not exist, install it:

```bash
~/agent/skills/skills-registry/scripts/skills-install proactive-check
```

### 4. Re-point the voice-loading line

Open `~/agent/skills/restart/SKILL.md`. If it has an `Adopt the voice:` line that still points at `core/skills/personality`, delete that whole line. Then run `~/agent/skills/personality/SETUP.md` step 1, which inserts the current voice-loading line (it reads the shared voice plus your active preset from the new location). If the line already points at `~/agent/skills/personality`, leave it.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-06-personality-out-of-core"`.
