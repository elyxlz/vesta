Catch-up migration for legacy agents. Two structural changes plus a general convergence pass:

- The restart prompt has moved into a `restart` skill at `~/agent/skills/restart/SKILL.md`.
- The personality skill no longer writes the active preset name into that file. Personality registers the voice-loading line via its own SETUP.md.

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

### 5. Run upstream-sync end to end

Run `~/agent/skills/upstream-sync/SKILL.md`. Things this brings forward in one shot:

- **Sparse-checkout self-heal** (step 1 of that skill). If your sparse pattern is still on the broad `/agent/` rule, it gets rewritten so `agent/skills/*/` is opt-in and only currently-installed skills are re-included. Future merges stop pulling in unrelated upstream skills.
- **Latest content for every installed skill.** Upstream's canonical SKILL.md / SETUP.md / scripts replace yours, with conflicts where you've made local edits.
- **Refreshed `agent/skills/index.json`** so `skills-search` reflects the current registry.
- **Restored root `.gitignore`** if missing.

Conflict resolution rules (in addition to the skill's standard guidance):

- `agent/skills/restart/SKILL.md`: you'll hit an add/add or modify/modify conflict because steps 1–3 just rewrote it. **Keep your local version verbatim** (it has the legacy body you want to preserve plus the voice-loading line from step 2). Drop upstream's canonical body.
- `agent/MEMORY.md`: see step 6.
- Everything else: follow the skill's "preserve both behaviors" rule.

### 6. Reconcile MEMORY.md with the upstream layout

`agent/MEMORY.md` will conflict during the merge. Both sides have changed: upstream has reshaped sections and added Charter rules over time (em-dash ban, URL verification before outbound messages, voice-vs-Charter split, etc.); locally you've accumulated User Profile, contacts, learned patterns.

Resolve by hand, treating the two versions as a manual merge:

- **Charter, section structure, scaffolding prose**: take upstream's wording. New rules join your Charter as-is. Where upstream has reorganized headings, follow upstream's layout.
- **§4 User Profile, §5 Learned Patterns, any prose you've added under existing sections**: keep your local content verbatim. This is the relationship, not template.
- **Lines where both sides edited the same content**: integrate, keep your specific facts, adopt upstream's framing.

Goal: the resolved file reads as the upstream layout filled with your accumulated knowledge. Not a wholesale revert, not a refusal to update structure.

### 7. Reconcile installed skills with the current registry

`agent/skills/index.json` (now refreshed) lists every skill in the upstream registry. `agent/skills/default-skills.txt` lists the current defaults baked into fresh agents. Compare against `ls ~/agent/skills/`:

- **Default skill not installed locally**: read its SKILL.md from the registry (without installing). Decide whether you want it. Default = yes, unless you have a reason to skip.
- **Locally installed skill not in the registry anymore**: an old skill that was retired upstream. Decide whether it's still useful: keep it on disk if yes; otherwise remove the directory and drop its sparse re-include.

This isn't about chasing every default, it's about closing the gap between what you have and what the current registry expects.

### 8. Mark this migration applied

Append the line `2026-05-restart-skill` to `~/agent/data/migrations.applied` (create the file if it doesn't exist). Use append mode, do not overwrite.
