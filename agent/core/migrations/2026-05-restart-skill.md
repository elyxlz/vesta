The restart prompt has moved into a `restart` skill at `~/agent/skills/restart/SKILL.md`. Apply this migration once.

**Idempotency.** If `~/agent/skills/restart/SKILL.md` already contains the line `<!-- migrated from prompts/restart.md -->`, skip steps 1–3 (the merge has already happened) and go straight to step 4.

### 1. Ensure the skill exists

If `~/agent/skills/restart/SKILL.md` does not exist (you are on an older container that predates the skill), create it with exactly this content:

````markdown
---
name: restart
description: What to do after a container restart, plus the user-managed list of services to bring back up.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

`screen -ls` to see what's already up. Start anything in `## Services` below that isn't. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

## Services

Skill setup steps add their service startup commands here, one fenced block per skill. Run each on every restart unless the corresponding screen session is already up.

```bash
# (empty until a skill registers a service)
```
````

(Use `mkdir -p ~/agent/skills/restart` first.)

### 2. Fold the legacy prompt in

If `~/agent/prompts/restart.md` exists, read it. Inside the existing `## Services` section of `~/agent/skills/restart/SKILL.md`, replace the placeholder fenced block (the one that just contains `# (empty until a skill registers a service)`) with the legacy file's content, wrapped like this:

```
<!-- migrated from prompts/restart.md -->
<legacy file content>
<!-- end migrated -->
```

If the legacy file's content already includes a `## Services` heading and surrounding prose, only carry over the fenced bash blocks under that heading — don't duplicate the workflow text. If you can't tell what's a service block and what's prose, paste the whole thing verbatim inside the marker comments and let a future dream pass clean it up.

### 3. Remove the legacy prompt

- `rm ~/agent/prompts/restart.md`
- `rmdir ~/agent/prompts` if it's empty

### 4. Mark this migration applied

Append the line `2026-05-restart-skill` to `~/agent/data/migrations.applied` (create the file if it doesn't exist). Use append mode, do not overwrite. This tells the migration runner not to queue this prompt again.
