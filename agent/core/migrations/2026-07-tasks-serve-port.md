`tasks daemon status` now reports liveness by curling the daemon's own HTTP port, which the
daemon records in `~/.tasks/serve.port` when it starts. A tasks daemon that has been running
since before this change never wrote that file, so `tasks daemon status` would report it down
even while it serves, and the restart guard (`running tasks ||`) sees the live `screen` session
and won't relaunch it. This migration restarts the tasks daemon once so it writes `serve.port`.
Safe to run more than once: it checks before acting and no-ops when already converged.

### 1. Skip if tasks isn't installed

```bash
grep -n 'screen -dmS tasks tasks serve' ~/agent/skills/restart/SKILL.md
```

If grep finds nothing (tasks daemon not installed, or you manage it differently), this
migration is done: go to the final step.

### 2. Skip if already converged

```bash
test -f ~/.tasks/serve.port && echo CONVERGED
```

If it prints `CONVERGED`, the port file already exists: go to the final step.

### 3. Restart the tasks daemon once

Quit the running session, then re-run its guarded startup line so it comes back and writes
`serve.port`:

```bash
screen -S tasks -X quit 2>/dev/null; screen -wipe >/dev/null 2>&1 || true
```

Then run the exact `running tasks || { ... tasks serve --port $PORT; sleep 1; }` line from the
`## Daemons` section of `~/agent/skills/restart/SKILL.md`. Confirm it converged:

```bash
tasks daemon status
```

It should print `"running": true`. If it still reports down, check `~/.tasks/logs/daemon.log`.
