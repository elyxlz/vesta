The tasks daemon line in your restart skill was documented without the `running <name> ||`
guard every Daemons line requires. Unguarded, it does two harmful things: `&&` short-circuits
and the daemon never starts if `register-service` times out, and re-running the block (crash
recovery re-enters it) stacks duplicate tasks daemons. This migration rewraps that one line.
Safe to run more than once: it checks before acting and no-ops when already converged.

### 1. Find the tasks daemon line

Only your restart skill's `## Daemons` section is affected:

```bash
grep -n 'screen -dmS tasks tasks serve' ~/agent/skills/restart/SKILL.md
```

If grep finds nothing (tasks daemon not installed, or you manage it differently), this
migration is done: skip to step 3.

### 2. Wrap it in the running guard

If the matched line is already wrapped in `running tasks ||`, this step is done. Otherwise
replace the whole line with the guarded form (keep any `--notifications-dir` or other flags
you personalized on it):

```
running tasks || { PORT=$(~/agent/skills/vestad/scripts/register-service tasks) && screen -dmS tasks tasks serve --port $PORT; sleep 1; }
```

The `running tasks ||` guard is defined at the top of the Daemons block, so it is in scope
here. Keep the `&&` between registration and start: a failed registration short-circuits so the
daemon never launches on a port vestad does not know about.

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-tasks-restart-guard"`.
