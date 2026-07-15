---
name: restart
description: What to do after a container restart. Holds the per-skill daemon startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

Run the Daemons block below; it is safe to re-run and starts only what's missing. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

## Daemons

Skill setup steps add their daemon startup commands here, one fenced block per skill (a daemon that vestad proxies on a port is a service, registered via the `vestad` skill; a portless background process still goes here). Every line MUST be guarded with `running <session> ||` so re-running the block can't spawn a duplicate: crash/timeout recovery re-enters this skill repeatedly, and an unguarded line piles up duplicate daemons.

```bash
# Wipe dead sockets a restart may have left in /run/screen, else the guard treats
# a "(Dead ???)" corpse as still-running and never restarts the daemon.
screen -wipe >/dev/null 2>&1 || true

# True iff a LIVE screen session with this exact name exists. Judge by captured
# output (test -n), not exit code: the agent's shimmed ugrep `grep -qv` returns 0
# on empty input, which would report every daemon as live on a cold boot.
running() { test -n "$(screen -ls 2>/dev/null | grep -E "[0-9]+\.$1[[:space:]]" | grep -v "Dead")"; }

# Skills append guarded startup lines below, e.g.:
#   running foo || { screen -dmS foo foo serve --notifications-dir ~/agent/notifications; sleep 1; }
# The trailing `sleep 1` keeps back-to-back `screen -dmS` launches from racing and dropping sessions.
```
