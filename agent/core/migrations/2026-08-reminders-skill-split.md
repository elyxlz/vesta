The reminders skill is now its own `cli/` uv project at `~/agent/skills/reminders/cli`. Its command `reminders` sets and manages time-based reminders. The tasks skill keeps tasks only. The reminders a box already has live in the tasks database at `~/.tasks/tasks.db`. The first `reminders` command on the box copies them into its own store at `~/.reminders/reminders.db`, once. This migration installs the `reminders` command, activates the reminders skill, starts its daemon, and gives it a restart line. Every step reads what is on disk first, so it is safe to run more than once.

### 1. Install the reminders command

```bash
uv tool install --editable --force ~/agent/skills/reminders/cli
command -v reminders
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
~/agent/skills/skills-registry/scripts/skills-activate reminders
```

### 4. Start the reminders daemon and give it a restart line

Starting the daemon is the first `reminders` command, so it runs the one-time copy out of `~/.tasks/tasks.db`:

```bash
reminders daemon start
reminders daemon status
```

Expect `{"running":true,"port":<n>}`. Then add one line to `~/agent/skills/restart/daemons.sh` so the daemon returns after a reboot, unless a `reminders daemon start` line is already there:

```bash
grep -qxF 'reminders daemon start' ~/agent/skills/restart/daemons.sh || echo 'reminders daemon start' >> ~/agent/skills/restart/daemons.sh
```

### 5. Restart the tasks daemon

Pick up the trimmed tasks code:

```bash
tasks daemon restart
tasks daemon status
```

### 6. Verify the reminders moved

```bash
reminders list --show-completed
```

This lists the reminders the box had before, recurring ones first. A box that never used reminders shows an empty list, which is correct.

If that list holds a recurring reminder whose message is about updating contacts and reconciling them across messaging apps and services (the nightly contacts pass), delete it by id with `reminders delete <id>`: the `dream` runs that pass now, and an earlier migration that removed it could only find it under the old `tasks remind` command. If there is none, nothing to do.

### 7. Carry your reminder patterns across

Look at the end of `~/agent/skills/tasks/SKILL.md`. If it still has a `### Reminder Patterns` section holding notes you wrote (not just the bare placeholder), move that body under `### Reminder Patterns` at the end of `~/agent/skills/reminders/SKILL.md`, then delete the section from the tasks file. If there is no such section, or only the placeholder, nothing to do.

### 8. Repoint your own notes

There is no `tasks remind` command: `tasks` refuses it with a usage error. Any note of yours that still spells it out is an instruction you will follow into that error, so find every one:

```bash
grep -rn 'tasks remind' ~/agent/MEMORY.md ~/agent/skills --exclude-dir=cli --exclude-dir=.venv
```

Rewrite each hit in place. `tasks remind "..." <flags>` becomes `reminders create "..." <flags>`; `tasks remind list|snooze|update|delete` becomes `reminders list|snooze|update|delete`. A `--task <id>` flag has no equivalent: drop it and name the task in the message instead. No hits means nothing to do.

Then sweep the reminders themselves, because the grep above cannot see them:

```bash
reminders list --json | grep -i 'tasks remind'
```

A recurring reminder's message is an instruction you act on when it fires, so a message spelling the
old command is a break exactly like a script is, except it lives in sqlite rather than the source
tree and surfaces only at fire time, in a hurry. Rewrite any hit with `reminders update <id>
--message '...'`, applying the same substitutions. No hits means nothing to do.

### 9. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-reminders-skill-split"`.

### 10. Restart to load the reminders skill

Activation only lists the skill; the boot entrypoint is what links it into `~/.claude/skills`, so until the next boot the daemon runs but the skill body is not in your skill list. Call `restart_vesta` now. Do it only after step 9, so this migration does not run again on the way back up.
