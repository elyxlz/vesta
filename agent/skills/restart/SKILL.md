---
name: restart
description: What to do after a container restart. Holds the per-skill daemon startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

Run the Daemons block below. Every command is guarded by `running <name> ||`, so running the whole block is always safe and starts only what's missing. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

On a fresh start only (after the nightly dream or a first start, not a mid-conversation resume or crash/timeout recovery), reason through your personality for the day. If the fresh start lands in the middle of the night, do not spend this into an empty room: note the deferral in one line and do the full reasoning at the day's first outward contact (the morning brief or their first message), when today's calendar and yesterday's residue are real, and let it set the register of that first message. Don't restate the rules: given what's on today and what you know about them, how will the voice genuinely show through, as the same message and not garnish on the work? Name two or three concrete openings (a callback, a contradiction worth teasing, a pattern you've clocked). This is what makes character stick instead of decaying into flat task-mode the moment work shows up.

## Daemons

Skill setup steps add their daemon startup commands here, one fenced block per skill (a daemon that vestad proxies on a port is a service, registered via the `service` skill; a portless background process still goes here).

Every line MUST be guarded with `running <session> ||` so re-running the block can't spawn a duplicate. This is load-bearing: crash/timeout recovery re-enters this skill repeatedly and a crash can interrupt the block partway, so an unguarded line piles up duplicate daemons (two of one poller wedge each other; many writing notifications swamp the event log).

```bash
# Dead sockets from a previous boot can linger in /run/screen (a restart that
# preserves /run leaves the old sessions behind, now marked "(Dead ???)"). The
# guard below would treat such a corpse as "still running" and never restart the
# daemon. Wipe them first so `running` reflects the true live state.
screen -wipe >/dev/null 2>&1 || true

# True iff a LIVE screen session with this exact name exists: keep the matching
# lines, drop any "(Dead ???)" corpse, and test that something LIVE remains.
# Trailing-whitespace match keeps `running whatsapp` false when only `whatsapp-elio` exists.
# Judge by captured output (test -n), never by a pipeline's exit code: the agent's
# `grep` is ugrep (the Bash tool's shell snapshot shims it), and ugrep's `grep -qv`
# returns 0 on EMPTY input -- so the obvious `... | grep -qv "Dead"` reports every
# daemon as live on a cold boot (zero screens) and skips every guarded launch.
# Filtering with `grep -v "Dead"` (not `grep -q "Dead"` negated) is also existential,
# so a live session is still seen as running even if a same-name corpse lingers.
running() { test -n "$(screen -ls 2>/dev/null | grep -E "[0-9]+\.$1[[:space:]]" | grep -v "Dead")"; }

# Skills append guarded startup lines below, e.g.:
#   running foo || { screen -dmS foo foo serve --notifications-dir ~/agent/notifications; sleep 1; }
# The trailing `sleep 1` is defensive: firing several `screen -dmS` back-to-back
# right after a reboot can race and silently drop sessions; a brief beat per launch
# makes them stick.
```
