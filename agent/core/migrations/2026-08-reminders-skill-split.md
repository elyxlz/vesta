The reminders skill is now its own `cli/` uv project at `~/agent/skills/reminders/cli`. Its command `remind` sets and manages time-based reminders. The tasks skill keeps tasks only. The reminders a box already has live in the tasks database at `~/.tasks/tasks.db`. The reminders daemon copies them into its own store at `~/.reminders/reminders.db` once, on its first start. This migration installs the `remind` command, activates the reminders skill, starts its daemon, and gives it a restart line. Every step reads what is on disk first, so it is safe to run more than once.

### 1. Install the reminders command

```bash
uv tool install --editable --force ~/agent/skills/reminders/cli
command -v remind
```

The second line must print a path under `~/.local/bin`. If it does not, STOP, leave this migration unmarked, and tell the user: the reminders daemon has nothing to run.

### 2. Reinstall the tasks command

The tasks project no longer carries the reminder scheduler, so refresh its environment:

```bash
uv tool install --editable --force ~/agent/skills/tasks/cli
command -v tasks
```

### 3. Activate the reminders skill

```bash
skills-activate reminders
```

### 4. Start the reminders daemon and give it a restart line

The daemon copies any existing reminders out of `~/.tasks/tasks.db` on its first start, so start it first:

```bash
remind daemon start
remind daemon status
```

Expect `{"running":true,"port":<n>}`. Then add one line to `~/agent/skills/restart/daemons.sh` so the daemon returns after a reboot, unless a `remind daemon start` line is already there:

```bash
grep -qxF 'remind daemon start' ~/agent/skills/restart/daemons.sh || echo 'remind daemon start' >> ~/agent/skills/restart/daemons.sh
```

### 5. Restart the tasks daemon

Pick up the trimmed tasks code:

```bash
tasks daemon restart
tasks daemon status
```

### 6. Verify the reminders moved

```bash
remind list --show-completed --limit 5
```

This lists the reminders the box had before. A box that never used reminders shows an empty list, which is correct.

### 7. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-reminders-skill-split"`.
