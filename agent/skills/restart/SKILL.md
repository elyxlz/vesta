---
name: restart
description: What to do after a container restart. Records active personality and per-skill service startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

Adopt the voice: read the preset name in `## Personality` below, then `Read` `~/agent/core/skills/personality/presets/<name>.md` and use it. That file is the source of truth for how you sound, not MEMORY.md.

`screen -ls` to see what's already up. Start anything in `## Services` below that isn't. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

## Personality

(empty until the personality skill records the active preset)

## Services

Skill setup steps add their service startup commands here, one fenced block per skill. Run each on every restart unless the corresponding screen session is already up.

```bash
# (empty until a skill registers a service)
```
