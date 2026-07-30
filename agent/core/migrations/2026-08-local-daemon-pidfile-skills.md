Audit every skill created on this box. Any skill that owns a background process must own the same
`<skill> daemon start|stop|restart|status` lifecycle as a shipping skill.

### 1. Review every skill you created

Review every locally created skill and identify any that run a persistent background process.
Include skills that are not currently present in the restart block; an omission there does not put
a daemon outside this migration. Keep a checklist so every locally created skill is accounted for
before marking the migration applied.

### 2. Give each local daemon the contract

Before changing any local skill, read both `~/agent/skills/vestad/SKILL.md` and
`~/agent/skills/skills-registry/SKILL.md` completely. The former defines the daemon contract; the
latter defines how a locally created skill owns, installs, documents, and registers its command.
Follow both.

For every locally created skill that runs a background process, implement the daemon contract in
the local skill itself, in its existing language:

- one command with `daemon start|stop|restart|status`
- JSON results and failure behavior exactly as the contract specifies
- pid and port records under `~/agent/data/daemons/`
- an appended log under `~/agent/logs/`
- exclusive, idempotent start; bounded ready and stop behavior; local status
- registration inside `start` when it serves a port, preserving whether the old service was public
  or private
- deliberate SIGTERM suppression if the process emits `daemon_died`

Use the shell, Python, or Go exemplar named by the vestad skill rather than designing a different
lifecycle. Preserve the local skill's existing arguments, environment, data paths, service name,
exposure, and notification behavior.

The command normally has the skill directory's name. A skill with a `cli/` project installs its
console script using its own installation mechanism. A skill without one exposes
`~/agent/skills/<skill>/<skill>` and links it into `~/.local/bin`. Do not link the old serve script
as the new command.

Before stopping anything, verify:

```bash
command -v <skill>
<skill> --help
<skill> daemon status
```

All three must succeed and status must print one JSON line. A legacy daemon that is still running
without a new pid record can correctly produce `"running":false` at this point.

If you cannot make a local daemon meet the contract, leave its old process and restart line intact,
record what remains, and continue with every other local skill. Never delete a local daemon or its
startup line just because it was absent from the shipping migration's table. After doing everything
you can, tell the user about any skills that could not be migrated and leave this migration
unmarked so it can retry later.

### 3. Hand over a running legacy process safely

For each converted local daemon, determine whether its old process is running from the launch line,
`screen -ls`, its old pid record, and the process list. Stop only the process you positively
identify as that skill's legacy daemon. Use its existing graceful stop when it has one; otherwise
end its screen session or send SIGTERM to its verified pid. Do not use a broad process-name kill.

Once the old process is gone, run:

```bash
<skill> daemon start <preserved non-lifecycle flags>
<skill> daemon status
```

Expect `started` and then `"running":true`. If start fails, read the new log, fix it, and restore
the daemon before proceeding. Do not leave a messaging, notification, or user-facing daemon down.

### 4. Repair the restart block

In `~/agent/skills/restart/SKILL.md`, replace each converted local daemon's legacy shell, screen,
serve, registration, sleep, and redirection line with its command alone:

```bash
<skill> daemon start <preserved non-lifecycle flags>
```

Preserve the behavior of every flag from the old launch. A setting may leave the restart line only
when the converted skill explicitly owns it and reads it from a documented persistent location;
move the value there before removing the flag. Otherwise keep the flag on the new command,
including a custom poll interval or notification path. If the skill is meant to survive restarts
but had no line, add one.

Re-read the block and compare it with the checklist from step 1. Every locally created daemon meant
to survive a restart must appear exactly once, and no local daemon may have silently disappeared.
Commit the local skill and restart-file changes so the next upstream merge preserves them.
