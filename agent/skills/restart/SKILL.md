---
name: restart
description: What to do after a container restart. Holds the per-skill daemon startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

Run `~/agent/skills/restart/start-daemons`. Do NOT retype the Daemons block below: it reaches you as a context snapshot that can be one line out of date, and a daemon added since that snapshot was taken then never comes back up while every line you can see reports green. The script reads the block from the file, which is the only copy that is current, and it is safe to re-run: it starts only what is missing. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

## Daemons

When a skill's setup gives you a daemon startup line, add it here yourself, inside the fenced block below, on its own line before the closing fence. A setup script never edits this file. (A daemon that vestad proxies on a port gets that port from its own `daemon start`; a portless background process goes here too.)

Every line is `<skill> daemon start`, with no guard around it (a trailing comment of your own, like `# TEMP` on a service you will tear down, is fine). A start is idempotent: a daemon that is already up answers `{"status":"already_running"}` and spawns nothing, so re-running this whole block cannot stack duplicates, which is what makes it safe for crash and timeout recovery to re-enter this skill repeatedly. A start also returns only once its daemon is actually up, so the lines never race each other and need no sleep between them.

Three flags never appear on a line, because the command applies them itself: a port, a `--notifications-dir`, and a poll interval. Every other flag a skill's setup gives you stays on the line, because it is something chosen for that daemon and the command cannot infer it. Whatsapp named instances are the case you will meet: one line per account, each keeping the `--instance <name>` and per-instance flags it was set up with, e.g. `whatsapp daemon start --instance personal --read-only`.

Keep every line in the one fenced block below, so a single read shows you every daemon this container runs. `start-daemons` parses exactly this block, so a line added here starts working on the next restart with nothing else to update.

```bash
# One line per daemon, e.g.:
#   file-host daemon start
```
