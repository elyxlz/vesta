The Claude Code task tools are now off, and vesta's `tasks` skill is the only task system. Move
anything still live out of the harness's store, then remove it.

### Why this is a migration and not just a config change

Core now sets `CLAUDE_CODE_ENABLE_TASKS=0` and denies `TodoWrite`, so `TaskCreate`, `TaskUpdate`,
`TaskGet`, `TaskList`, `TaskStop` and `TaskOutput` are unavailable from this boot onward. If you
used them, that state is now stranded: it is still on disk, still yours, and nothing will read it
back to you.

It also mattered more than duplication. Every call wrote a JSON file under `~/.claude/tasks/`, and
the harness re-injected that whole list into your context as a system-reminder **on every turn**.
So an old pile did not merely sit on disk, it steadily shaped what you surfaced, and the influence
was hard to trace back to its source. On one box it reached about a hundred files accumulated over
weeks, several of them long dead, and the symptom that exposed it was the owner asking why his
agent kept raising things he could not place.

### 1. Check whether you have anything to migrate

```
ls ~/.claude/tasks/ 2>/dev/null | wc -l
```

**If the directory does not exist, or is empty, you have nothing to move.** Say so and mark the
migration applied. Many agents never called these tools and this is a no-op for them; that is a
clean result, not a failed check.

### 2. Read every file before deleting anything

Each file is one task as JSON. Read them all. For each, decide honestly whether it is **still
genuinely open**:

- a real commitment, a live deadline, or something the user is waiting on -> it moves
- done, abandoned, superseded, or a scratch note from a task that ended weeks ago -> it does not

Do not migrate the whole pile to be safe. The point of this is to stop dead items following you
around; copying them into a new store defeats it. If you cannot tell what an item meant, that is
itself evidence it is dead.

### 3. Move the live ones into the vesta tasks skill

Read `~/agent/skills/tasks/SKILL.md` first, then create each surviving item with the `tasks` CLI,
carrying over its title, any due date, and enough of the detail to be actionable. Put the substance
in task metadata rather than cramming it into the title.

**Only give a due date to something that genuinely has one.** An item with no real deadline goes in
undated (`--backburner` if it should not show as stale), because a fabricated due date generates
reminder fires about work that was never scheduled.

### 4. Remove the harness store

Once the live items exist in the `tasks` CLI and you have confirmed them with `tasks list`:

```
rm -rf ~/.claude/tasks/
```

### 5. Note it where it will be read

If your memory or any skill file tells you to use `TaskCreate`/`TodoWrite`, or describes the
harness task tools as available, correct it now. Otherwise you will keep reaching for a tool that
no longer answers.

This migration is safe to run again: after step 4 the directory is gone, so a re-run stops at
step 1.
