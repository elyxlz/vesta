Every daemon is driven by one command named after its skill, `<skill> daemon start|stop|restart|status`,
and runs as a plain detached process that records its own pid under `~/agent/data/daemons/`. A start
registers the port when the daemon needs one, launches it, and returns only once it is actually up;
it is idempotent, so a live pid answers `already_running` and spawns nothing. That is what lets a
restart line be the command alone, with no guard around it.

This migration points each daemon line at its command, hands each running daemon over to it, and
reduces your restart lines to that form. Convert only the daemons you actually run. Every step
checks before acting and no-ops when already converged, so it is safe to run more than once.

### 1. Confirm the commands are on disk before touching anything

```bash
ls ~/agent/skills/ssh/ssh-tunnel
```

If that path does not exist, your workspace sync has not merged yet. STOP here and do NOT call
`mark_migration_applied`: this migration runs again on your next boot, and converting now would stop
your daemons with nothing able to start them again. Nothing else is needed once it does exist, since
agent startup puts every skill's command on PATH on every boot.

### 2. Find your daemon lines

```bash
grep -n 'daemon start\|screen -dmS\|serve\|register-service\|scripts/' ~/agent/skills/restart/SKILL.md
screen -ls
```

The first tells you which daemons you run, the second which of them are running the old way, in a
screen session. If both come back empty, skip to step 6.

### 3. The command for each launch

The command is not always the skill's directory name, so take it from this table rather than
guessing:

| if the launch runs | the command is |
| --- | --- |
| `tasks serve` | `tasks daemon start` |
| `google serve` | `google daemon start` |
| `microsoft serve` | `microsoft daemon start` |
| `slack serve` | `slack daemon start` |
| `discord serve` | `discord daemon start` |
| `tricount serve` | `tricount daemon start` |
| `agentmail serve` | `agentmail daemon start` |
| `app-chat serve` | `app-chat daemon start` |
| `voice serve` or `voice-keys serve` | `voice-keys daemon start` |
| `spotify organize watch` | `spotify daemon start` |
| `finance_cli.transaction_watcher serve` | `finance daemon start` |
| `moneypot/server.py` | `moneypot daemon start` |
| `file-host/serve.py` | `file-host daemon start` |
| `sign-service/sign_server.py` | `sign-service daemon start` |
| `whatsapp serve` or `whatsapp start` | `whatsapp daemon start`, keeping any `--instance` and other serve flags the old line carries |
| `telegram serve` | `telegram daemon start` |
| `telegram-watchdog.sh` | nothing: delete that line, `telegram daemon start` brings the watchdog up too |
| `poll_daemon.py` or `email-client daemon start --interval N` | `email-client daemon start` |
| `~/agent/skills/dashboard/scripts/serve` or `scripts/daemon start` | `dashboard daemon start` |

### 4. Hand each running daemon over, one at a time

A daemon inside a screen session is invisible to its command: there is no pid record, so
`<skill> daemon status` reports `"running":false` while the daemon is very much alive, and a start
would put a second copy beside it. So end the session first, then start through the command. For
each daemon:

```bash
screen -S <session> -X quit
sleep 2
<the command from step 3>
<skill> daemon status
```

Expect `{"status":"started"}` then `{"running":true,...}`. A start that answers with an error left
nothing running: read `~/agent/logs/<skill>.log`, fix what it names, and start again before moving
on, especially for a messaging daemon, since that is the user's channel to you. A whatsapp or
telegram start compiles its CLI first and can take minutes; let it finish.

Session names are not always the skill name, so take them from `screen -ls`; these are the ones in
the fleet:

| skill | session(s) |
| --- | --- |
| tasks, google, microsoft, slack, discord, tricount, agentmail, moneypot, file-host, sign-service, dashboard, app-chat, voice, email-client | the skill's own name |
| spotify | `spotify-watch` |
| enable-banking | `finance` |
| whatsapp | `whatsapp`, plus `whatsapp-<instance>` for each extra instance |
| telegram | `telegram` and `telegram-watchdog`; quit both, and `telegram daemon start` brings both back |

A `bore-ssh` session is an ssh tunnel rather than one of these daemons: quit it and follow step 6,
which is a different flow.

Then clear the records the old lifecycles kept, so nothing reads a pid that is gone:

```bash
rm -f ~/.tasks/serve.pid ~/.tasks/stop-requested \
      ~/.google/serve.pid ~/.google/stop-requested \
      ~/.microsoft/serve.pid ~/.microsoft/stop-requested \
      ~/.app-chat/stop-requested ~/.telegram/stop-requested \
      ~/.email-client/daemon.pid ~/.email-client/daemon-info.json \
      ~/.email-client/stop-requested ~/.email-client/poll_daemon.log
```

### 5. Reduce every restart line to its command

Open the `## Daemons` section of `~/agent/skills/restart/SKILL.md` and make each line the command
from step 3, alone:

```
tasks daemon start
```

The shell around the launch goes: a `running <name> ||` guard, a `screen -dmS`, a `$PORT` capture, a
`register-service` call, a script path, a trailing `sleep 1`, a log redirection. A trailing comment
of your own may stay, such as a `# TEMP` marking a service you will tear down.

**Exactly three flags go, and every other flag stays.** The three the command now applies itself:

- a port (`--port N`), registered by the start
- `--notifications-dir`, which is `~/agent/notifications`
- `email-client`'s `--interval`, which lives in `EMAIL_CLIENT_POLL_INTERVAL` in `~/.bashrc` when the
  user wants a cadence other than the default

Anything else on the line is a choice the user made for that daemon, so it stays exactly as written.
A whatsapp instance line is the case that makes this concrete: it names an account, and dropping its
flags would both leave that account never starting again and make the line a duplicate of the
default one.

```
whatsapp daemon start --instance personal --read-only --no-notifications
```

The default whatsapp line takes no flags, and both lines belong in the block, one per instance.

Then delete the block's preamble: the `screen -wipe` line, the `running()` function definition, and
the comments explaining them. Nothing calls `running` once the lines are their commands. What is
left is the fenced block holding one start per daemon, and nothing else.

Verify with a re-read:

```bash
grep -n 'screen\|register-service\|||' ~/agent/skills/restart/SKILL.md
```

Expect no matches at all.

### 6. If you use the ssh tunnel

The tunnel is `ssh-tunnel`, with authorizing a key split out from running the tunnel, and it has no
line in the Daemons block: bore hands out a new public port on every start, so a tunnel restored by
itself after a restart would be listening at an address nobody has. Bring it up when the user asks
for it, and delete any Daemons line that starts one. Authorize the client key and start sshd once
with `ssh-tunnel setup "<the ssh-ed25519 line>"`, then run the tunnel with `ssh-tunnel daemon start`
and read the current port out of `~/agent/logs/ssh-tunnel.log` to give the user. Nothing to convert
if no tunnel is set up.

### 7. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-daemon-pidfile"`.
