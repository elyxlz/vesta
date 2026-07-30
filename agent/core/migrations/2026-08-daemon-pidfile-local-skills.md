The daemon-contract migration covered Vesta's shipping skills, but it did not make the scope of
locally created skills explicit enough. Audit every skill created on this box now. Any of those
skills that owns a background process must own the same `<skill> daemon
start|stop|restart|status` lifecycle as a shipping skill.

### 1. Find every locally created skill

Find the newest shipping tag merged into this checkout, list the skill directories it contains,
then compare that list with the directories on disk:

```bash
UPSTREAM_TAG=$(git -C ~ tag --merged HEAD --list 'agent-v*' --sort=-v:refname | head -1)
if [ -z "$UPSTREAM_TAG" ]; then
  echo "STOP: no merged agent-v tag"
else
  comm -23 \
    <(find ~/agent/skills -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort) \
    <(git -C ~ ls-tree -d --name-only "$UPSTREAM_TAG":agent/skills | sort)
fi
```

If there is no merged `agent-v` tag or its `agent/skills` tree cannot be read, STOP, leave this
migration unmarked, and tell the user. An incomplete shipping list could misclassify every stock
skill as local.

The output is the audit list. Do not narrow it using the restart skill: a locally created daemon
may have been omitted from that file by mistake. For every directory in the audit list, read its
`SKILL.md`, `SETUP.md`, executable or CLI entry point, and any serve/watch/worker scripts. Decide
from the skill itself whether it starts a persistent background process. Keep a checklist of every
local skill and that decision; inspect all of them before marking this migration applied.

Also read the full `## Daemons` block in `~/agent/skills/restart/SKILL.md` and run `screen -ls`.
Use those as additional evidence for local daemons and their old launch commands, including a
daemon whose skill docs are incomplete.

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
STOP HERE, leave this migration unmarked, and tell the user exactly what remains. Never
delete a local daemon or its startup line just because it was absent from the shipping migration's
table.

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

Remove only lifecycle flags the command now owns: the port, `--notifications-dir`, and a poll
interval moved to the environment according to the contract. Preserve every other flag because it
is local configuration. If the skill is meant to survive restarts but had no line, add one.

Re-read the block and compare it with the checklist from step 1. Every locally created daemon meant
to survive a restart must appear exactly once, and no local daemon may have silently disappeared.
Commit the local skill and restart-file changes so the next upstream merge preserves them.
