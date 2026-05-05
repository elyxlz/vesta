The restart prompt has moved into a `restart` skill at `~/agent/skills/restart/SKILL.md`, and the personality skill no longer writes the active preset name into that file (it reads `$AGENT_SEED_PERSONALITY` directly). Apply this migration once.

**Idempotency.** Each step states its own condition. Check before acting; if the condition is already satisfied, skip that step.

### 1. Ensure the skill exists

If `~/agent/skills/restart/SKILL.md` does not exist (older container that predates the skill), install it from upstream via the skills registry. This adds it to the sparse-checkout cone and pulls the canonical file from `$VESTA_UPSTREAM_REF` as a tracked file:

```bash
~/agent/skills/skills-registry/scripts/skills-install restart
```

### 2. Drop the legacy `## Personality` block

If the existing `~/agent/skills/restart/SKILL.md` contains a `## Personality` heading (predates the `AGENT_SEED_PERSONALITY` refactor), `Edit` the file:

- Remove the `## Personality` heading and everything beneath it up to (but not including) the next `##` heading.
- If the body does not already contain a line starting with `Adopt the voice:`, insert this paragraph (with a blank line on either side) immediately above the `## Services` heading:

```
Adopt the voice: `Read` `~/agent/core/skills/personality/presets/$AGENT_SEED_PERSONALITY.md` and use it. That file is the source of truth for how you sound, not MEMORY.md.
```

If there is no `## Personality` heading and the `Adopt the voice:` line is already present, this step is a no-op.

### 3. Copy the legacy prompt into the skill

If `~/agent/prompts/restart.md` exists, replace the body of `~/agent/skills/restart/SKILL.md` (everything after the YAML frontmatter) with the legacy file's content verbatim. Step 4 deletes the legacy file, so this step is naturally idempotent on a re-run.

### 4. Remove the legacy prompt

If `~/agent/prompts/restart.md` exists:

- `rm ~/agent/prompts/restart.md`
- `rmdir ~/agent/prompts` if it's empty

### 5. Mark this migration applied

Append the line `2026-05-restart-skill` to `~/agent/data/migrations.applied` (create the file if it doesn't exist). Use append mode, do not overwrite. This tells the migration runner not to queue this prompt again.
