---
name: restart
description: What to do after a container restart. Holds the per-skill daemon startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

Run the Daemons block below; it is safe to re-run and starts only what's missing. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

On a fresh start only (after the nightly dream or a first start, not a mid-conversation resume or crash/timeout recovery), reason through your personality for the day. If the fresh start lands in the middle of the night, do not spend this into an empty room: note the deferral in one line and do the full reasoning at the day's first outward contact (the morning brief or their first message), when today's calendar and yesterday's residue are real, and let it set the register of that first message. Don't restate the rules: given what's on today and what you know about them, how will the voice genuinely show through, as the same message and not garnish on the work? Name two or three concrete openings (a callback, a contradiction worth teasing, a pattern you've clocked). This is what makes character stick instead of decaying into flat task-mode the moment work shows up.

## Daemons

Skill setup steps add their daemon startup commands here, one fenced block per skill (a daemon that vestad proxies on a port is a service, registered via the `vestad` skill; a portless background process still goes here).

Every line MUST be guarded with `running <session> ||` so re-running the block can't spawn a duplicate. This is load-bearing: crash/timeout recovery re-enters this skill repeatedly, and an unguarded line piles up duplicate daemons.

```bash
# Wipe dead sockets a restart may have left in /run/screen, else the guard treats
# a "(Dead ???)" corpse as still-running and never restarts the daemon.
screen -wipe >/dev/null 2>&1 || true

# True iff a LIVE screen session with this exact name exists. Judge by captured
# output (test -n), not exit code: the agent's shimmed ugrep `grep -qv` returns 0
# on empty input, which would report every daemon as live on a cold boot.
running() { test -n "$(screen -ls 2>/dev/null | grep -E "[0-9]+\.$1[[:space:]]" | grep -v "Dead")"; }
# IMPORTANT: copy this definition verbatim from this file; never type it from
# memory or a system-reminder cache. A stale cached grep form matches nothing
# against a real session name, so running() returns false for a live session
# and `false || spawn` re-spawns on every guarded restart line, silently
# stacking duplicate daemons.

# Skills append guarded startup lines below, e.g.:
#   running foo || { screen -dmS foo foo serve --notifications-dir ~/agent/notifications; sleep 1; }
# The trailing `sleep 1` keeps back-to-back `screen -dmS` launches from racing and dropping sessions.
```
