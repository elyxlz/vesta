---
name: personality
description: Swap or refine the core identity block in MEMORY.md. Bundles a few starting-point presets the user can ask for by name, and supports freeform blends ("more sarcastic, still warm") or point edits ("stop using emojis").
---

# Personality

The agent's personality lives in the first H2 of `~/agent/MEMORY.md` (the `## 1. CORE IDENTITY & PERSONALITY` section). It's part of the system prompt on every turn. Presets are starting points, not fixed states. It's fine, and expected, for the personality to drift with the relationship.

## When to use this skill

- User asks to switch personality ("be more like a bro", "try the bff vibe", "make it sardonic again").
- User asks to adjust a specific trait ("stop using emojis", "tone down the sarcasm").
- First start, if `AGENT_PERSONALITY` is set in `/run/vestad-env`, apply that preset before anything else.

Freeform requests are fine, presets aren't required. The point is the section in MEMORY.md ends up matching what the user wants.

## Presets

Each preset lives at `~/agent/skills/personality/presets/<name>.md`. The file has a short HTML-comment frontmatter (`<!-- emoji: ... -->`, `<!-- title: ... -->`, `<!-- description: ... -->`) followed by the body to place under the identity H2. Every `[agent_name]` placeholder must be substituted with the agent's actual name.

Currently shipped: `default`, `girl-bff`, `boy-bff`. List them with `ls ~/agent/skills/personality/presets/`. Read one to see its body.

## Applying a preset

1. `Read` the preset file.
2. Skip the leading `<!-- key: value -->` lines and any blank lines.
3. Substitute every `[agent_name]` with the actual agent name.
4. `Edit` `~/agent/MEMORY.md`: replace the body under `## 1. CORE IDENTITY & PERSONALITY` (everything between that header and the next `## ` header) with the substituted preset body. Leave the H2 header itself intact. Leave everything outside that section alone.
5. Confirm the change in one short message.

## Freeform tweaks

If the user wants a blend ("keep my rules, adopt the bff warmth") or a point edit, don't nuke the whole section. Read the current identity block, make the minimal edit that matches the ask, save. Small surgical edits beat wholesale replacements.

## Not your job

Don't touch the other sections of MEMORY.md from this skill (security, channels, user state, learned patterns). Personality changes only alter the first H2 body.
