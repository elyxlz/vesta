Every daemon runs as a plain detached process that records its own pid under
`~/agent/data/daemons/`, and `<skill> daemon start|stop|restart|status` is the only way to drive
one. A start is idempotent (a live pid answers `already_running` and spawns nothing) and returns
only once the daemon is actually up, so a restart line is the bare command with no guard around
it. This migration hands each daemon you run over to its own command and reduces your restart
lines to that bare form. Every step checks before acting and no-ops when already converged, so it
is safe to run more than once.

### 1. Confirm the commands are on disk before touching anything

```bash
ls ~/agent/skills/dashboard/dashboard
```

If that path does not exist, your workspace sync has not merged yet. STOP here and do NOT call
`mark_migration_applied`: this migration runs again on your next boot, and converting now would
stop your daemons with nothing able to start them again.

### 2. Find your daemon lines

```bash
grep -n 'daemon start\|serve\|register-service\|scripts/' ~/agent/skills/restart/SKILL.md
screen -ls
```

The first tells you which daemons you run, the second which of them are running the old way, in a
screen session. If both come back empty, skip to step 5.

### 3. Hand each running daemon over, one at a time

A daemon inside a screen session is invisible to its command: there is no pid record, so
`<skill> daemon status` reports `"running":false` while the daemon is very much alive, and a start
would put a second copy beside it. So end the session first, then start through the command. For
each daemon:

```bash
screen -S <session> -X quit
sleep 2
<skill> daemon start
<skill> daemon status
```

Expect `{"status":"started"}` then `{"running":true,...}`. Session names are not always the skill
name, so take them from `screen -ls`; these are the ones in the fleet:

| skill | session(s) |
| --- | --- |
| tasks, google, microsoft, slack, discord, tricount, agentmail, moneypot, file-host, sign-service, dashboard, app-chat, voice, email-client | the skill's own name |
| spotify | `spotify-watch` |
| enable-banking | `finance` |
| whatsapp | `whatsapp`, plus `whatsapp-<instance>` for each extra instance |
| telegram | `telegram` and `telegram-watchdog`; quit both, and `telegram daemon start` brings both back |

A `bore-ssh` session is an ssh tunnel rather than a daemon of the list above: quit it and follow
step 5, which is a different flow.

Two things that can go wrong here:

- A daemon that ignores SIGHUP survives the quit, because a screen quit sends nothing stronger.
  `<skill> daemon status` reporting `"running":false` while the port is busy is that orphan. Find
  it with `ss -ltnp`, end it through its own CLI, and never with a bare `kill`.
- A start that reports an error left nothing running: read `~/agent/logs/<skill>.log`, fix what it
  names, and start again. Do not move on to the next daemon with this one down, especially a
  messaging daemon, since that is the user's channel to you.

Then clear the records the old lifecycles kept, so nothing reads a pid that is gone:

```bash
rm -f ~/.tasks/serve.pid ~/.tasks/stop-requested \
      ~/.google/serve.pid ~/.google/stop-requested \
      ~/.microsoft/serve.pid ~/.microsoft/stop-requested \
      ~/.app-chat/stop-requested ~/.telegram/stop-requested \
      ~/.email-client/daemon.pid ~/.email-client/daemon-info.json \
      ~/.email-client/stop-requested ~/.email-client/poll_daemon.log
```

### 4. Reduce every restart line to the bare command

Open the `## Daemons` section of `~/agent/skills/restart/SKILL.md` and reduce each line to the bare
command:

```
<skill> daemon start
```

Whatever else the line holds now, a `running <name> ||` guard, a `screen -dmS`, a `$PORT` capture, a
`register-service` call, a script path, a trailing `sleep 1`, personal flags, a log redirection:
all of it goes. The command registers the port, applies the defaults, and writes to
`~/agent/logs/<skill>.log`. A trailing comment of your own may stay, such as a `# TEMP` marking a
service you will tear down.

Two flags worth naming, because dropping them changes nothing you rely on: `email-client daemon
start` takes no `--interval` (set `EMAIL_CLIENT_POLL_INTERVAL` in `~/.bashrc` if the user wants a
cadence other than the default, and note IMAP IDLE means the interval is only a fallback), and no
line passes `--notifications-dir` any more.

Then delete the block's preamble: the `screen -wipe` line, the `running()` function definition,
and the comments explaining them. Nothing calls `running` once the lines are bare. What is left is
the fenced block holding one bare start per daemon, and nothing else.

Verify with a re-read:

```bash
grep -n 'screen\|register-service\|||' ~/agent/skills/restart/SKILL.md
```

Expect no matches at all.

### 5. If you use the ssh tunnel

The tunnel is `ssh-tunnel` now, with authorizing a key split out from running the tunnel, and the
old `~/agent/skills/ssh/scripts/*.sh` scripts are gone. Authorize the client key and bring up sshd
once with `ssh-tunnel setup "<the ssh-ed25519 line>"`, then run the tunnel with
`ssh-tunnel daemon start`. bore picks a new public port on every start, so read it from
`~/agent/logs/ssh-tunnel.log` and give the user the current one. Nothing to convert if no tunnel
is set up.

### 6. Mark this migration applied

Call `mark_migration_applied` with `name="2026-08-daemon-pidfile"`.
