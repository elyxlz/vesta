Service startup now distinguishes claiming a port from resolving an already-running
service. Your persisted tasks restart line predates that distinction, so update it
to request a bindable port before tasks starts. Safe to run more than once.

### 1. Update the tasks restart line

Inspect the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:

```bash
grep -n 'register-service tasks' ~/agent/skills/restart/SKILL.md
```

If the matching line starts tasks and already includes the `--claim` flag, it is
converged. Otherwise, add `--claim` immediately after `tasks` while preserving
the line's existing guard, notifications directory, and other personalized
flags. The result should resemble:

```
running tasks || { PORT=$(~/agent/skills/vestad/scripts/register-service tasks --claim) && screen -dmS tasks tasks serve --port $PORT; sleep 1; }
```

If no tasks registration exists, there is nothing to update.

### 2. Update other persisted service starts

Check the same Daemons section for AgentMail and File Host:

```bash
grep -nE 'register-service (agentmail|file-host)' ~/agent/skills/restart/SKILL.md
```

For each line that starts that service, add `--claim` after the service name if
it is missing. Preserve `--public`, the existing `running <name> ||` guard, and
all personalized arguments. Do not add `--claim` to a line that only resolves
the port of an already-running service.

If neither registration exists, this step is done.

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-bindable-service-ports"`.
