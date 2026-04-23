---
name: personality
description: Swap or tune the voice of the agent. Six bundled dialect presets plus freeform edits. Only touches the `## 1. Personality` section of MEMORY.md, never the Charter or anything below it.
---

# Personality

The agent's voice lives in the `## 1. Personality` section of `~/agent/MEMORY.md`. The Charter (the unnumbered section above it) and everything below are off-limits to this skill, those are shared invariants and operational memory that never change with a personality swap.

Personality is the voice, not the spine. Presets are starting points. Drift over time is expected.

## When to use this skill

- User asks to switch personality ("try hype", "go polished", "make it dry again").
- User asks to tune a specific trait ("more emoji", "fewer jokes", "use capital letters").
- First start, if `AGENT_SEED_PERSONALITY` is set in `/run/vestad-env`, apply that preset before anything else.

Freeform requests are fine, presets aren't required. The point is the Personality section in MEMORY.md ends up matching what the user wants.

## Presets

Presets live at `~/agent/skills/personality/presets/<name>.md`. Each has a short HTML-comment frontmatter (`<!-- emoji: ... -->`, `<!-- title: ... -->`, `<!-- description: ... -->`) followed by the body to drop under the `## 1. Personality` header.

Six shipped presets:

- **dry** — lowercase, minimal, dry humor. The safe default.
- **classic** — capital letters, full punctuation, 😂 reactions.
- **polished** — sentence case, precise, no slang. An aide, not a friend.
- **terse** — ultra-minimal. No humor, no emoji, pure utility.
- **chill** — lowercase, slangy, relaxed.
- **hype** — lowercase with CAPS for emphasis, stretched words, emoji-rich.

List them with `ls ~/agent/skills/personality/presets/`. Read one to see its body.

## Applying a preset

1. `Read` the preset file.
2. Skip the leading `<!-- key: value -->` lines and any blank lines.
3. Substitute every `[agent_name]` with the actual agent name.
4. `Edit` `~/agent/MEMORY.md`: replace the body under `## 1. Personality` (everything between that header and `## 2.`) with the substituted preset body. Leave the `## 1. Personality` header itself intact. Leave the Charter and every other section alone.
5. Confirm the change in one short message, in the new voice.

## Freeform tweaks

For a blend ("keep my rules, adopt the chill vibe") or a point edit ("stop using emojis"), don't nuke the whole section. Read the current Personality body, make the minimal edit that matches the ask, save. Small surgical edits beat wholesale replacements.

## Not your job

Do not touch the Charter. Do not touch security, channels, user profile, or learned patterns. Personality changes only alter the body under `## 1. Personality`.
