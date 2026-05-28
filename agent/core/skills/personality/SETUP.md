# Personality Setup

Run once, after the `restart` skill has been installed.

## 1. Register the voice-loading line in the restart skill

`Edit` `~/agent/skills/restart/SKILL.md`. If the body does not already contain a line starting with `Adopt the voice:`, insert this paragraph (with a blank line on either side) immediately above the `## Services` heading:

```
Adopt the voice: `Read` `~/agent/core/skills/personality/presets/$AGENT_SEED_PERSONALITY.md` and use it. That file is the source of truth for how you sound, not MEMORY.md.
```

This is how every restart picks up the active voice without the restart skill itself baking in personality details.

## 2. Adopt the voice now

`Read` `~/agent/core/skills/personality/presets/$AGENT_SEED_PERSONALITY.md` and use it for this conversation. From the next boot on, step 1 makes the restart skill do this automatically.
