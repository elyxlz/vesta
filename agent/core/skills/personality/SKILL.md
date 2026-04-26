---
name: personality
description: Swap or tune the agent's voice; edits only MEMORY.md's Personality section.
---

# Personality

Voice, not spine. Presets are starting points, drift with the relationship is expected.

## When

- User asks to switch ("try extra", "make it dry") or tune ("fewer emoji", "use capital letters").
- First start, with `$AGENT_SEED_PERSONALITY` from `/run/vestad-env`.

## Presets

Live in `~/agent/core/skills/personality/presets/`. `ls` lists what's shipped, `Read` one for its body.

## Apply a preset

Each preset starts with a YAML frontmatter block delimited by `---`, then the body:

```
---
emoji: 😏
title: dry
description: ...
---

### Voice
...
```

1. `Read` the preset file.
2. Skip the YAML frontmatter (everything between the first two `---` lines) and the blank line after. Take everything from the first `###` onward.
3. `Edit` `~/agent/MEMORY.md`: replace the body under `## 1. Personality` (everything between that header and `## 2.`) with that body. Keep the `## 1. Personality` header. Leave the Charter and every other section alone.
4. Confirm in one short message, in the new voice.

## Freeform

For blends or point edits, don't rewrite the whole section. Read the current body, make the minimal edit, save.
