Every skill that runs a daemon owns its own lifecycle behind one command named after the skill,
`<skill> daemon start|stop|restart|status`. Start registers the port when the daemon needs one,
launches it, and returns only once it is actually up; stop signals the process itself and counts
as the deliberate shutdown, so it reports no crash. Your restart skill can therefore launch each
daemon with one short command instead of registering a port and driving the launch by hand.

Convert only the daemons you actually run. Safe to run more than once: it checks before acting and
no-ops when already converted.

### 1. Find your daemon lines

```bash
grep -n 'daemon start\|serve\|register-service\|scripts/' ~/agent/skills/restart/SKILL.md
```

If grep finds nothing, skip to the final step.

### 2. Confirm the new commands are on disk before converting anything

```bash
ls ~/agent/skills/dashboard/dashboard
```

If that path does not exist, your workspace sync has not merged yet, so the commands the next step
writes would not resolve. STOP here and do NOT call `mark_migration_applied`: this migration runs
again on your next boot, and converting before the sync would leave every daemon line pointing at a
command that is not there. Nothing else is needed once it does exist, since agent startup puts each
skill's command on PATH on every boot.

### 3. Point each launch at the skill's own command

For each matched line, replace ONLY the launch, the part of the line that starts the daemon. Leave
the rest of the line alone for now; the next migration in this batch reduces every line to the bare
command.

| if the launch runs | replace it with |
| --- | --- |
| `tasks serve` | `tasks daemon start` |
| `google serve` | `google daemon start` |
| `microsoft serve` | `microsoft daemon start` |
| `slack serve` | `slack daemon start` |
| `discord serve` | `discord daemon start` |
| `tricount serve` | `tricount daemon start` |
| `agentmail serve` | `agentmail daemon start` |
| `app-chat serve` | `app-chat daemon start` |
| `voice-keys serve` | `voice-keys daemon start` |
| `spotify organize watch` | `spotify daemon start` |
| `finance_cli.transaction_watcher serve` | `finance daemon start` |
| `moneypot/server.py` | `moneypot daemon start` |
| `file-host/serve.py` | `file-host daemon start` |
| `sign-service/sign_server.py` | `sign-service daemon start` |
| `whatsapp serve` or `whatsapp start` | `whatsapp daemon start` |
| `telegram serve` | `telegram daemon start` |
| `telegram-watchdog.sh` | delete that line: `telegram daemon start` brings the watchdog up too |
| `poll_daemon.py` or `email-client daemon start --interval N` | `email-client daemon start` |
| `~/agent/skills/dashboard/scripts/serve` or `scripts/daemon start` | `dashboard daemon start` |

Worked example. If your line reads:

```
running tasks || { PORT=$(register-service tasks) && tasks serve --port $PORT; sleep 1; }
```

it becomes:

```
running tasks || { tasks daemon start; sleep 1; }
```

If your launch carried personal flags (a `--notifications-dir`, a `--interval`, a log redirection,
a port), drop them: the command applies the same defaults, the port is registered for you, and the
log goes to `~/agent/logs/<skill>.log`.

### 4. Verify each command answers

For each daemon you converted, ask its command how it is doing:

```bash
tasks daemon status
```

Expect one line of JSON, `{"running":...}`. That is what this step checks: the command resolves and
answers, so the converted line will work. It can report `"running":false` while your daemon is
still up, because each command tracks the process its own start launched; the next migration in this
batch hands the running process over. Do not stop or restart anything here.

### 5. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-daemon-lifecycle"`.
