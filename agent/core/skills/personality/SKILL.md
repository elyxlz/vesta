---
name: personality
description: The agent's voice. One file per option in presets/, edit directly to drift it.
---

# Personality

Voice, not spine. Each file in `presets/` is a complete personality, the source of truth for how the agent sounds. The active one is whichever matches `$AGENT_SEED_PERSONALITY` in `/run/vestad-env`, picked at agent creation. The `restart` skill loads it on every boot.

## Files

`~/agent/core/skills/personality/presets/*.md`. Each file owns its full voice: YAML frontmatter (emoji, title, description, sample, order), then the body (`### Voice`, `### Rules`, `### How it sounds`).

`ls` to see what's available, `Read` `presets/$AGENT_SEED_PERSONALITY.md` for the active one.

## Drift / tweak

The active file is the source of truth. To bend the voice (fewer emoji, more capital letters, a new opener), `Edit` `presets/$AGENT_SEED_PERSONALITY.md` in place. Surgical edits, not rewrites. The Charter in MEMORY.md is off-limits, that's the invariant spine.
