---
name: personality
description: The agent's voice. Pick one on first start; edit the file directly to drift it.
---

# Personality

Voice, not spine. Each file in `presets/` is a complete personality, the source of truth for how the agent sounds. The active one is recorded in the `restart` skill's `## Personality` section and re-read on every restart.

## Files

`~/agent/core/skills/personality/presets/*.md`. Each file owns its full voice: YAML frontmatter (emoji, title, description, sample, order), then the body (`### Voice`, `### Rules`, `### How it sounds`).

`ls` to see what's available, `Read` one for its body.

## Pick one (first start, or a swap)

1. Resolve the name. First start: `$AGENT_SEED_PERSONALITY` from `/run/vestad-env`. Swap: the user's request ("try dry", "switch to chill").
2. `Read` `~/agent/core/skills/personality/presets/<name>.md` to confirm it exists and to load the voice into context.
3. `Edit` `~/agent/skills/restart/SKILL.md`: replace the contents of the `## Personality` section with a single line naming the active preset, e.g. `classic`.
4. Adopt the voice immediately. If swapping, confirm in one short message in the new voice.

## Drift / tweak

The active file is the source of truth. To bend the voice (fewer emoji, more capital letters, a new opener), `Edit` the preset file in place. Surgical edits, not rewrites. The Charter in MEMORY.md is off-limits, that's the invariant spine.
