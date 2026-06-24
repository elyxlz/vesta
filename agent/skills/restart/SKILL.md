---
name: restart
description: What to do after a container restart. Holds the per-skill daemon startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

`screen -ls` to see what's already up, then run the Daemons block below. The block is idempotent (every command is guarded by `running <name> ||`), so running the whole thing is always safe and starts only what is missing. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

On a fresh start only (after the nightly dream or a first start, not a mid-conversation resume or crash/timeout recovery), reason through your personality for the day before anything else. Don't restate the rules: given what's on today and what you know about them, how will the voice genuinely show through, as the same message and not garnish on the work? Name two or three concrete openings (a callback, a contradiction worth teasing, a pattern you've clocked). This is what makes character stick instead of decaying into flat task-mode the moment work shows up.

## Daemons

Skill setup steps add their daemon startup commands here, one fenced block per skill (a daemon that vestad proxies on a port is a service, registered via the `service` skill; a portless background process still goes here).

Every startup command MUST be idempotent: guard it with `running <session> ||` so re-running this block can never spawn a duplicate. This is structural, not something the agent has to remember to check, and it matters because the loop re-enters this skill on every crash/timeout recovery and a crash can interrupt the block partway through. An unguarded block then piles up duplicate daemons on each pass: two of one WhatsApp/Telegram poller wedge each other (StreamReplaced, or getUpdates 409 Conflict), and many duplicated daemons all writing notifications can swamp the event log. The `running` helper below makes "start only if not already up" automatic; when a skill adds a daemon it appends a guarded line.

```bash
# Always available: true if a screen session with this exact name is already running.
# The trailing-whitespace match keeps `running whatsapp` false when only `whatsapp-elio` exists.
running() { screen -ls 2>/dev/null | grep -qE "[0-9]+\.$1[[:space:]]"; }

# Skills append guarded startup lines below, e.g.:
#   running foo || screen -dmS foo foo serve --notifications-dir ~/agent/notifications
```
