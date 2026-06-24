---
name: restart
description: What to do after a container restart. Holds the per-skill daemon startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

`screen -ls` to see what's already up. Start anything in the Daemons section below that isn't. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

On a fresh start only (after the nightly dream or a first start, not a mid-conversation resume or crash/timeout recovery), reason through your personality for the day before anything else. Don't restate the rules: given what's on today and what you know about them, how will the voice genuinely show through, as the same message and not garnish on the work? Name two or three concrete openings (a callback, a contradiction worth teasing, a pattern you've clocked). This is what makes character stick instead of decaying into flat task-mode the moment work shows up.

## Daemons

Skill setup steps add their daemon startup commands here, one fenced block per skill (a daemon that vestad proxies on a port is a service, registered via the `service` skill; a portless background process still goes here). Run each on every restart unless the corresponding screen session is already up.

```bash
# (empty until a skill adds a daemon)
```
