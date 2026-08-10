---
name: restart
description: What to do after a container restart. Starts the per-skill daemons this container runs.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

Run `~/agent/skills/restart/start-daemons.sh`. It brings up every daemon this container runs and is safe to re-run: it starts only what is down. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

## Daemons

The daemons this container runs live in `~/agent/skills/restart/daemons.sh`, one line per daemon. `start-daemons.sh` reads that file and runs every line, so the file is the one source of truth. Never retype these lines from memory, and never hand-start a daemon that belongs in the file.

When a skill's setup gives you a daemon startup line, add it to `daemons.sh` yourself, on its own line. Create the file if it does not exist. A setup script never edits it. (A daemon that vestad proxies on a port gets that port from its own `daemon start`; a portless background process goes in the file too.)

Every line runs, so a line that is not a working daemon command is reported as a failure on stderr, never silently skipped. A start is idempotent: a daemon already up answers `{"status":"already_running"}` and spawns nothing, so re-running cannot stack duplicates, which is what makes it safe for crash and timeout recovery to re-enter this skill. A start also returns only once its daemon is actually up, so the lines never race and need no sleep between them.

Three flags never appear on a line, because the command applies them itself: a port, a `--notifications-dir`, and a poll interval. Every other flag a skill's setup gives you stays on the line, because it is chosen for that daemon and the command cannot infer it. Whatsapp named instances are the case you will meet: one line per account, each keeping the `--instance <name>` and per-instance flags it was set up with.

`daemons.sh` holds one `<skill> daemon start` per line, with `#` comment lines allowed. For example:

```bash
#!/usr/bin/env bash
# One <skill> daemon start per line. The restart skill runs each line.
whatsapp daemon start --instance personal --read-only
file-host daemon start
```
