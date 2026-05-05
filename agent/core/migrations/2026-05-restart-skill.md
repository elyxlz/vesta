The restart prompt has moved into a `restart` skill at `~/agent/skills/restart/SKILL.md`, and the personality skill no longer writes the active preset name into that file (it reads `$AGENT_SEED_PERSONALITY` directly).

### 1. Install the restart skill

Install it from upstream via the skills registry. This adds it to the sparse-checkout cone and pulls the canonical file from `$VESTA_UPSTREAM_REF` as a tracked file:

```bash
~/agent/skills/skills-registry/scripts/skills-install restart
```

### 2. Drop the legacy `## Personality` block, register the voice via personality SETUP

If `~/agent/skills/restart/SKILL.md` contains a `## Personality` heading (predates the `AGENT_SEED_PERSONALITY` refactor), `Edit` the file to remove the heading and everything beneath it up to (but not including) the next `##` heading.

Then run `~/agent/core/skills/personality/SETUP.md` to insert the voice-loading line and adopt the voice.

### 3. Copy the legacy prompt into the skill

If `~/agent/prompts/restart.md` exists, replace the body of `~/agent/skills/restart/SKILL.md` (everything after the YAML frontmatter) with the legacy file's content verbatim.

### 4. Remove the legacy prompt

- `rm ~/agent/prompts/restart.md`
- `rmdir ~/agent/prompts` if it's empty

### 5. Mark this migration applied

Append the line `2026-05-restart-skill` to `~/agent/data/migrations.applied` (create the file if it doesn't exist). Use append mode, do not overwrite.
