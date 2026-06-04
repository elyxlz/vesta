Catch-up migration for legacy agents. Brings old state into the current shape and pulls in current upstream content. Safe to run more than once: for each step, check whether you're already in the desired end state and no-op if so.

Some agents ran an earlier convergence that left their git state messy: vestad-managed files committed to the branch, or extra skills on disk. The sync in step 3 detects and fixes that automatically.

### 1. Install the restart and timezone skills

```bash
~/agent/skills/skills-registry/scripts/skills-install restart
~/agent/skills/skills-registry/scripts/skills-install timezone
```

The `timezone` skill replaces the old `set_timezone` MCP tool.

### 2. Move the restart prompt and register the voice

If `~/agent/skills/restart/SKILL.md` still has a `## Personality` heading (predates the `AGENT_SEED_PERSONALITY` refactor), remove that heading and everything under it up to the next `##`. Then follow `~/agent/skills/personality/SETUP.md` to register the voice (the `personality` skill moved out of core; if it is not installed yet, the `2026-06-personality-out-of-core` migration installs it).

If `~/agent/prompts/restart.md` exists, replace the body of the restart SKILL (everything after the frontmatter) with it verbatim, then remove `~/agent/prompts/restart.md` and `rmdir ~/agent/prompts` if it's empty.

### 3. Sync with upstream

Run the upstream sync. It does the mechanical cleanup for you (narrows a broad sparse cone, stops tracking the vestad-managed `agent/core`/`pyproject.toml`/`uv.lock`, merges current upstream content, refreshes the skills registry):

```bash
~/agent/skills/upstream-sync/scripts/sync.sh
```

It only stops for real content conflicts (exit code 2, with the files listed). Resolve each preserving both your behavior and upstream's, then run `sync.sh` again to finish. Notes for this migration:

- Keep your local `restart` SKILL if it conflicts (steps 1 and 2 just set it up); drop upstream's version.
- For `MEMORY.md`, see step 5.
- You do not need to hand-fix committed core or an unrelated history; `sync.sh` handles both.

See `~/agent/skills/upstream-sync/SKILL.md` for details.

### 4. Trim your skill set

`sync.sh` narrows the cone, but if an old broad checkout left registry skills on disk that you never installed, drop them: keep the container defaults (`~/agent/skills/default-skills.txt`), the ones you installed with `skills-install`, and any you authored yourself; remove the rest (`git rm` them if a past run committed them). Your own skills aren't in `~/agent/skills/index.json` and are yours to keep.

### 5. Reconcile MEMORY.md

If `MEMORY.md` conflicts during the sync, keep your accumulated knowledge and adopt upstream's structure and any new rules where it changed. Don't wholesale-revert to the template, and don't refuse the new structure.

### 6. Mark this migration applied

Call `mark_migration_applied` with `name="2026-06-workspace-resync"`.
