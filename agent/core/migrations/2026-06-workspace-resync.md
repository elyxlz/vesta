Catch-up migration for legacy agents. Brings old state into the current shape and pulls in current upstream content. Safe to run more than once: for each step, check whether you're already in the desired end state and no-op if so.

Some agents ran an earlier convergence that left their git state messy: vestad-managed files committed to the branch, or extra skills on disk. If that's you, this run should detect and fix it.

### 1. Install the restart and timezone skills

```bash
~/agent/skills/skills-registry/scripts/skills-install restart
~/agent/skills/skills-registry/scripts/skills-install timezone
```

The `timezone` skill replaces the old `set_timezone` MCP tool.

### 2. Move the restart prompt and register the voice

If `~/agent/skills/restart/SKILL.md` still has a `## Personality` heading (predates the `AGENT_SEED_PERSONALITY` refactor), remove that heading and everything under it up to the next `##`. Then follow `~/agent/core/skills/personality/SETUP.md` to register the voice.

If `~/agent/prompts/restart.md` exists, replace the body of the restart SKILL (everything after the frontmatter) with it verbatim, then remove `~/agent/prompts/restart.md` and `rmdir ~/agent/prompts` if it's empty.

### 3. Sync with upstream

Run `~/agent/skills/upstream-sync/SKILL.md` to pull current upstream content for your installed skills and core and resolve conflicts. Specific to this migration:

- Keep your local `restart` SKILL (steps 1 and 2 just set it up); drop upstream's version if it conflicts.
- Resolve real conflicts the normal way, preserving both your behavior and upstream's.
- If the merge floods you with conflicts because your branch and upstream share no common ancestor (this happens when the repo was recreated), don't grind through them. Re-anchor instead: take the upstream tree as your new base and re-apply your own files on top (your `MEMORY.md`, your installed skills, your `.gitignore`). You still pull in all the new upstream content, you just skip the false conflicts.
- `agent/core/`, `agent/pyproject.toml`, and `agent/uv.lock` are vestad-managed and bind-mounted read-only. If a previous run committed any of them onto your branch, stop tracking them now and keep them skip-worktree'd. Never commit them.

### 4. Trim your skill set

After the sync, keep on disk and tracked: the skills that ship with the container (`~/agent/skills/default-skills.txt`), the ones you deliberately installed with `skills-install`, and any skills you created yourself. Drop only the spillover: skills that exist in the upstream registry (`~/agent/skills/index.json`) but you never installed, which landed on disk from an old broad checkout. Remove those from the sparse checkout, and `git rm` them if a past run committed them, so they're gone from disk and from your diff. Leave your own skills alone; they aren't in the upstream registry and are yours to keep.

### 5. Reconcile MEMORY.md

`MEMORY.md` will likely conflict. Keep your accumulated knowledge and adopt upstream's structure and any new rules where it changed. Don't wholesale-revert to the template, and don't refuse the new structure.

### 6. Mark this migration applied

Call `mark_migration_applied` with `name="2026-06-workspace-resync"`.
