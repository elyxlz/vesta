The vestad helper scripts are on PATH as bare commands, linked into `~/.local/bin` by agent
startup on every boot: `register-service`, `user-notification`, and `vestad-health` (the
`health` script, under a name specific enough not to collide with anything else in the image).
Their full paths keep working, so this migration is a readability pass over the daemon lines in
your restart skill and nothing else. Every step checks before acting and no-ops when there is
nothing to change, so it is safe to run more than once.

### 0. Skip if no daemon line spells out a helper path

```bash
grep -n 'skills/vestad/scripts/' ~/agent/skills/restart/SKILL.md 2>/dev/null
```

If that comes back empty, there is nothing to do: call `mark_migration_applied` with
`name="2026-07-vestad-helpers-on-path"` and STOP.

### 1. Check the bare commands resolve

```bash
command -v register-service user-notification vestad-health
```

Rewrite only the paths whose bare command this prints. Anything it does not print stays spelled
out as a full path, which runs exactly as it does today.

### 2. Rewrite those paths in the daemon lines

Edit `~/agent/skills/restart/SKILL.md` with your editor tools, one occurrence at a time, and
substitute inside each daemon line:

- `~/agent/skills/vestad/scripts/register-service` becomes `register-service`
- `~/agent/skills/vestad/scripts/user-notification` becomes `user-notification`
- `~/agent/skills/vestad/scripts/health` becomes `vestad-health`

The same paths may be written as `$HOME/agent/skills/vestad/scripts/...` or
`/root/agent/skills/vestad/scripts/...`; those forms substitute the same way.

Change nothing else on a line, whatever shape it has: leave every guard, launch, `$PORT` capture,
port, path, flag, log location, and trailing command exactly as you find them. A daemon line is
yours, so the helper's name is the only thing this touches. So if a line reads:

```
PORT=$(~/agent/skills/vestad/scripts/register-service tasks) && <the rest of your line, untouched>
```

it becomes:

```
PORT=$(register-service tasks) && <the rest of your line, untouched>
```

### 3. Verify

```bash
grep -n 'skills/vestad/scripts/' ~/agent/skills/restart/SKILL.md
```

What is left should be only the helpers step 1 did not print. Running daemons are untouched:
the rewritten lines are read at the next restart.

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-vestad-helpers-on-path"`.
