---
migration_phase: before_sync
---

Your restart skill lists its daemons in a fenced bash block inside `~/agent/skills/restart/SKILL.md`. The restart skill now reads them from their own file, `~/agent/skills/restart/daemons.sh`. Move the lines there. Do this now, before the workspace syncs, so the daemon lines are captured before the merge rewrites `SKILL.md`. Safe to run more than once: it checks for the new file first and no-ops once the move is done.

### 1. Stop if already moved

```bash
test -f ~/agent/skills/restart/daemons.sh && echo done || echo todo
```

If it prints `done`, skip to step 4.

### 2. Copy the daemon lines into daemons.sh

Read `~/agent/skills/restart/SKILL.md`. Inside the fenced ```bash block under `## Daemons`, every line that is not a `#` comment and not blank is a daemon this container runs. Copy them all verbatim, keeping every flag, into `~/agent/skills/restart/daemons.sh` under this header:

```bash
#!/usr/bin/env bash
# One <skill> daemon start per line. The restart skill runs each line.
```

If the block holds only `#` comment lines (this container runs no daemons of its own), write `daemons.sh` with just that header and no command lines.

### 3. Restore the block in SKILL.md to its placeholder

So the coming sync merges `SKILL.md` cleanly, replace everything between the block's ```bash fence and its closing fence with exactly these two lines, dropping the daemon lines you just copied:

```
# One line per daemon, e.g.:
#   file-host daemon start
```

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-restart-daemons-file"`.
