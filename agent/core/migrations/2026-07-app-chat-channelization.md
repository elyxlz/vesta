The app-chat conversation moved out of core, both out of core's transport and out of the read-only
core mount: app-chat is now a normal installed skill under `~/agent/skills/` (like whatsapp and
telegram, personalizable and surviving upgrades) that owns its own store and serves its own /message
and /history as a registered service. This migration installs the skill at its new home, re-points
its editable CLI there (the old `~/agent/core/skills/app-chat/cli` vanishes on this update), imports
your existing app-chat history into the skill store (preserving ids so the app's chat scroll stays
seamless, and indexing it so `app-chat history --search` still finds old messages), and repoints your
restart Daemons line at the new serve/register form. Safe to run more than once: every step checks
before acting.

### 0. Install the app-chat skill at its new home

If `~/agent/skills/app-chat/cli/pyproject.toml` does not exist, install the skill:

```bash
~/agent/skills/skills-registry/scripts/skills-install app-chat
```

If it still does not exist after that, STOP HERE and do NOT mark applied: the upstream sync later
this boot brings the moved skill into your workspace history, and this migration re-runs on the next
boot once it is present.

### 1. Re-point the app-chat CLI at its new source (picks up serve/register + import)

Your app-chat tool may still be an editable install pointing at the old
`~/agent/core/skills/app-chat/cli`, which is gone after this update. Reinstall it from the new source
so `app-chat` keeps working:

```bash
uv tool install --editable --force --reinstall ~/agent/skills/app-chat/cli
```

This is transactional: a failed rebuild leaves the existing tool exactly as it was.

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
