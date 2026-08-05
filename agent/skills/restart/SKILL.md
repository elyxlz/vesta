---
name: restart
description: What to do after a container restart. Holds the per-skill daemon startup commands.
---

# Restart

Read `/run/vestad-env` so the values are in your context (Read tool, not bash).

Run the Daemons block below; it is safe to re-run and starts only what's missing. Then check User State in MEMORY.md and reach out on their preferred channel. Match the moment: new day → warm; mid-convo restart → brief; crash → mention it; middle of the night → wait.

## Daemons

When a skill's setup gives you a daemon startup line, add it here yourself, inside the fenced block below, on its own line before the closing fence. A setup script never edits this file. (A daemon that vestad proxies on a port gets that port from its own `daemon start`; a portless background process goes here too.)

Every line is `<skill> daemon start`, with no guard around it (a trailing comment of your own, like `# TEMP` on a service you will tear down, is fine). A start is idempotent: a daemon that is already up answers `{"status":"already_running"}` and spawns nothing, so re-running this whole block cannot stack duplicates, which is what makes it safe for crash and timeout recovery to re-enter this skill repeatedly. A start also returns only once its daemon is actually up, so the lines never race each other and need no sleep between them.

Three flags never appear on a line, because the command applies them itself: a port, a `--notifications-dir`, and a poll interval. Every other flag a skill's setup gives you stays on the line, because it is something chosen for that daemon and the command cannot infer it. Whatsapp named instances are the case you will meet: one line per account, each keeping the `--instance <name>` and per-instance flags it was set up with, e.g. `whatsapp daemon start --instance personal --read-only`.

Keep every line in the one fenced block below, so a single read shows you every daemon this container runs.

```bash
# One line per daemon, e.g.:
#   file-host daemon start
```

## Two container facts, if you ever build your own boot-time guard

Sooner or later you will want a belt-and-braces layer that brings daemons back without waiting for
a turn, and the obvious shape is a "run once per boot" guard in `~/.bashrc` marked by a file in
`/tmp`. Both halves of that instinct are wrong on this image, and neither failure announces itself:
the guard simply stops running while continuing to look correct.

**`/tmp` is NOT a tmpfs, so a restart does not clear it.** It is part of the container's writable
layer, which `docker restart` preserves, so a marker written there survives every restart. A guard
written as "once per boot" is therefore "once in the container's lifetime": it fires on the first
boot and never again. Check yours rather than assuming:

```bash
findmnt -no FSTYPE,TARGET /tmp    # no output means /tmp is on the writable layer, not a tmpfs
ls -lat --time-style=long-iso /tmp | tail -5   # entries older than this boot prove it persists
```

**`/proc/uptime` is the HOST kernel's, not this container's**, so it cannot tell you whether you
just booted or have been up for weeks, and it will happily read in days while the container is
minutes old. The oracle is PID 1's creation time:

```bash
stat -c %y /proc/1     # when THIS container actually started
```

If you do build such a guard, key it to something that really changes: a staleness window (re-run
when the marker is older than N seconds), or PID 1's start time. And validate it by replay in both
directions, since a guard that never fires and a guard that fires correctly look identical from
outside: kill a daemon with a stale marker and confirm it comes back, then confirm a fresh marker
does not re-run it on every shell.
