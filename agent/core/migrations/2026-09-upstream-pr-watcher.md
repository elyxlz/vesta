The `upstream` skill runs a watcher, `upstream daemon start`, that polls the PRs this agent opened every five minutes and delivers what changed on them (a comment, a check result, a merge, a close) as `source=upstream` notifications. It comes back after a container restart only from a line in `~/agent/skills/restart/daemons.sh`. Safe to run more than once: every step reads disk state first.

### 1. Confirm the command has its daemon verbs

```bash
upstream daemon status
```

It must print a `{"running": ...}` line. If it prints usage or `command not found`, reinstall the command with `uv tool install --editable --force ~/agent/skills/upstream/cli` and run it again. If it still fails, STOP, leave this migration unmarked, and report it to the user.

### 2. Add the restart line if it is missing

Read `~/agent/skills/restart/daemons.sh`. If no line is exactly `upstream daemon start`, add one on its own line. Create the file with the header the `restart` skill documents if it does not exist. Change no line that is already there.

### 3. Start the watcher

```bash
upstream daemon start
```

It prints `{"status":"started"}` or `{"status":"already_running"}`. Its first pass records the PRs you have open and reports nothing; changes from then on arrive as notifications.

### 4. Mark this migration applied

Call `mark_migration_applied` with `name="2026-09-upstream-pr-watcher"`.
