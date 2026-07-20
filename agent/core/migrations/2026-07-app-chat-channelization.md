The app-chat conversation moved out of core: the app-chat skill now owns its own store and serves
its own /message and /history as a registered service, like whatsapp and telegram. This migration
imports your existing app-chat history into the skill store (preserving ids so the app's chat scroll
stays seamless, and indexing it so `app-chat history --search` still finds old messages) and repoints
your restart Daemons line at the new serve/register form. Safe to run more than once: every step
checks before acting.

### 0. Wait for the new app-chat CLI

If `app-chat import --help` does not list the `import` command, STOP HERE and do NOT mark applied:
the upstream sync later this boot brings it, and this migration re-runs on the next boot.

### 1. Reinstall the app-chat CLI (picks up serve/register + import)

```bash
uv tool install --editable ~/agent/core/skills/app-chat/cli
```

### 2. Import existing history (idempotent, id-preserving, indexes for search)

```bash
app-chat import
```

The report shows rows imported (0 on a fresh agent, which is fine).

### 3. Repoint the restart Daemons line

In `~/agent/skills/restart/SKILL.md` under `## Daemons`, replace any `app-chat daemon start` or
`screen -dmS app-chat app-chat serve` line with the guarded service form:

```bash
running app-chat || { app-chat daemon start; sleep 1; }
```

`app-chat daemon start` now registers the `app-chat` service and starts the HTTP server plus ws.
If the line already matches, this step is done.

### 4. Bring the daemon up as the registered service

```bash
app-chat daemon restart
```

This re-registers the `app-chat` service and restarts the HTTP server plus ws on its registered
port, replacing the old in-place daemon without a container restart.
