Every skill that runs a daemon owns its own lifecycle behind one command,
`<skill> daemon start|stop|restart|status`. Start registers the port when the daemon needs one,
launches it, and waits until it is actually up. Stop signals the process itself and marks the
shutdown as deliberate, so it no longer reports a crash. Your restart skill can therefore launch
each daemon with one short command instead of registering a port and driving `screen` by hand.

Convert only the daemons you actually run. Safe to run more than once: it checks before acting and
no-ops when already converted.

### 1. Find your daemon lines

```bash
grep -n 'screen -dmS\|register-service\|whatsapp start' ~/agent/skills/restart/SKILL.md
```

If grep finds nothing, skip to the final step.

### 2. Put the launchers on PATH

`moneypot`, `file-host`, `sign-service` and `dashboard` run their daemons through a command of the
same name. Link whichever of them you use, so the lines you write in the next step resolve. Safe to
re-run, and harmless for a skill you do not use:

```bash
mkdir -p ~/.local/bin
for s in moneypot file-host sign-service dashboard; do
  [ -f ~/agent/skills/$s/$s ] && ln -sf ~/agent/skills/$s/$s ~/.local/bin/$s
done
```

### 3. Replace each launch, keeping your own guard

For each matched line, replace ONLY the launch command, the part your guard runs when the daemon is
missing. Keep your guard exactly as it is: this file is yours, and your guard may not be the stock
`running <name> ||` form.

| if the launch runs | replace it with |
| --- | --- |
| `tasks serve` | `tasks daemon start` |
| `google serve` | `google daemon start` |
| `microsoft serve` | `microsoft daemon start` |
| `slack serve` | `slack daemon start` |
| `discord serve` | `discord daemon start` |
| `tricount serve` | `tricount daemon start` |
| `agentmail serve` | `agentmail daemon start` |
| `spotify organize watch` | `spotify daemon start` |
| `finance_cli.transaction_watcher serve` | `finance daemon start` |
| `moneypot/server.py` | `moneypot daemon start` |
| `file-host/serve.py` | `file-host daemon start` |
| `sign-service/sign_server.py` | `sign-service daemon start` |
| `whatsapp start` | `whatsapp daemon start` |
| `~/agent/skills/dashboard/scripts/daemon start` | `dashboard daemon start` |

Worked example. If your line reads:

```
running tasks || { PORT=$(~/agent/skills/vestad/scripts/register-service tasks) && screen -dmS tasks tasks serve --port $PORT; sleep 1; }
```

it becomes:

```
running tasks || { tasks daemon start; sleep 1; }
```

If your guard is a different shape, keep that shape and swap only the launch. If your launch
carried personal flags (a `--notifications-dir`, a log redirection, a port), drop them: the new
command applies the same defaults, and the port is registered for you.

`whatsapp start` keeps working, so that row can never break you whether you convert it or not.

### 4. Check moneypot's exposure, if you run it

The API key file now decides whether moneypot is public: it registers public when
`~/agent/data/moneypot-api-key` exists, private when it does not.

- Ran it privately: nothing changes.
- Ran it publicly with an API key: nothing changes, same port and same key, now read from the file.
- Ran it publicly with NO key: it was serving an open API through your tunnel. It becomes private.
  If an external caller genuinely needs in, create the key file and give that caller the key.

### 5. Verify, without restarting anything

For each daemon you converted, confirm the new command sees the daemon already running. Daemons are
identified by their screen session, so this works against a session started the old way:

```bash
tasks daemon status
```

Expect JSON reporting `"running":true`. Do this for each converted skill. Nothing restarts and
nothing is dropped, so a daemon mid-work keeps working.

If one reports `"running":false` while `screen -ls` shows the session alive, your session name
differs from that skill's default; leave that line alone and keep the launch you had.

### 6. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-daemon-lifecycle"`.
