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

### 2. Confirm the lifecycle is on disk before converting anything

```bash
ls ~/agent/skills/vestad/scripts/daemon-lifecycle
```

If that path does not exist, your workspace sync has not merged yet, so the commands the next step
writes would not resolve. STOP here and do NOT call `mark_migration_applied`: this migration runs
again on your next boot, and converting before the sync would leave every daemon line pointing at a
command that is not there. Nothing else is needed once it does exist, since agent startup puts each
skill's command on PATH on every boot.

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
| `~/agent/skills/dashboard/scripts/serve` | `dashboard daemon start` |

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

### 4. Verify each converted daemon

For each daemon you converted, ask its own command how it is doing:

```bash
tasks daemon status
```

Expect JSON reporting `"running":true`: the daemon is up and the new command sees it, so nothing
restarts and a daemon mid-work keeps working.

If one reports `"running":false` while `screen -ls` still shows a session for it, that daemon is
running outside what its command tracks. Quit the session and start it through the command:

```bash
screen -S <session> -X quit
tasks daemon start
```

Then re-check `tasks daemon status` and expect `"running":true`.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-daemon-lifecycle"`.
