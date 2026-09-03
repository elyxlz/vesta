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

A `FAILED` line is yours to handle before you move on. Run that one daemon's line from `daemons.sh` again yourself: a start can fail on transient host load and come up clean moments later, and the retry is safe because a failed start removes its own pid and port records. If the second attempt also fails, read `~/agent/logs/<name>.log`, find the cause, and fix it yourself. Bring in the user only when the fix needs something only they can provide (a credential, a re-link, a decision), and ask for exactly that. A daemon left down fails silently from then on: messages land nowhere and reminders never fire.

Three flags never appear on a line, because the command applies them itself: a port, a `--notifications-dir`, and a poll interval. Every other flag a skill's setup gives you stays on the line, because it is chosen for that daemon and the command cannot infer it. Whatsapp named instances are the case you will meet: one line per account, each keeping the `--instance <name>` and per-instance flags it was set up with.

`daemons.sh` holds one `<skill> daemon start` per line, with `#` comment lines allowed. For example:

```bash
#!/usr/bin/env bash
# One <skill> daemon start per line. The restart skill runs each line.
whatsapp daemon start --instance personal --read-only
file-host daemon start
```

## After restarting a MESSAGING daemon, go and look for what arrived while it was dead

**Backfill is partial, so a restart is not the end of the recovery.** Verified case: a whatsapp
daemon was found `"running": false` by a routine check, having died at some point earlier in the day.
The user had sent **three voice notes** in that window. On restart the daemon produced a notification
for **exactly one of the three**. The other two generated nothing: no notification, no error, and no
gap in any record to show something was missing. They were found only by chance, in a
`last_message_time` field printed by an unrelated command.

A dead daemon plus inbound media is a message that disappears completely, because notifications are
written only while the daemon lives and media never surfaces on its own afterwards. So whenever a
messaging daemon comes back from `running: false`, query its message store directly instead of
trusting backfill:

```bash
python3 - <<'PY'
import sqlite3
db = sqlite3.connect('/root/.whatsapp/messages.db')   # adjust per messaging skill
q = """SELECT timestamp, chat_jid, is_from_me, media_type, substr(coalesce(content,''),1,120)
       FROM messages WHERE timestamp > date('now','-1 day') ORDER BY timestamp"""
for r in db.execute(q):
    print(r)
PY
```

Anything inbound you have not already acted on is a message the user believes they sent you. Media
is the case that matters most: inbound attachments generally are not downloaded until something asks
for them, retention windows on the provider side are measured in days rather than weeks, and a
channel whose media was never fetched looks identical to a channel that was empty.
