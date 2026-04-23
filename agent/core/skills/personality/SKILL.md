---
name: personality
description: Swap or tune the voice of the agent. Only touches the `## 1. Personality` section of MEMORY.md, never the Charter or anything below.
---

# Personality

Voice, not spine. Presets are starting points, drift with the relationship is expected.

## When

- User asks to switch ("try girl-hype", "make it dry") or tune ("fewer emoji", "use capital letters").
- First start, with `$AGENT_SEED_PERSONALITY` from `/run/vestad-env`.

## Presets

Live in `~/agent/skills/personality/presets/`. `ls` lists what's shipped, `Read` one for its body.

## Apply a preset

Each preset starts with HTML-comment frontmatter, then the body:

```
<!-- emoji: 😏 -->
<!-- title: dry -->
<!-- description: ... -->

### Voice
...
```

1. `Read` the preset file.
2. Skip the `<!-- ... -->` comments and the blank line. Take everything from the first `###` onward.
3. Substitute every `[agent_name]` with the actual agent name.
4. `Edit` `~/agent/MEMORY.md`: replace the body under `## 1. Personality` (everything between that header and `## 2.`) with the substituted body. Keep the `## 1. Personality` header. Leave the Charter and every other section alone.
5. Confirm in one short message, in the new voice.

## Freeform

For blends or point edits, don't rewrite the whole section. Read the current body, make the minimal edit, save.
