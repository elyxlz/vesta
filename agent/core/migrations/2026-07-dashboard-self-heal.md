Your dashboard's startup command runs `vite preview`, which serves the prebuilt
`app/dist/`. But `dist/` and `node_modules/` are untracked build artifacts: if a
workspace sparse-checkout prune (or a clean) drops them while the box keeps
running, `vite preview` serves 404 for every route with no rebuild and no health
signal. The dashboard skill now ships `scripts/serve`, a launcher that rebuilds
`node_modules`/`dist` when missing before starting preview, so the service
self-heals on the next restart instead of serving nothing.

This migration repoints your restart daemon line at that launcher. It only
matters if you actually set up a dashboard. Safe to run more than once.

### 1. Repoint the dashboard daemon line

Open `~/agent/skills/restart/SKILL.md`. If its `## Daemons` section has no line
mentioning `dashboard`, you never set one up, skip to the final step.

If a dashboard line exists (it runs `screen -dmS dashboard ... vite preview ...`),
replace that whole line with:

```
running dashboard || { screen -dmS dashboard ~/agent/skills/dashboard/scripts/serve; sleep 1; }
```

If your line already reads exactly that, leave it, there is nothing to change.

### 2. Heal the running dashboard now (only if set up)

So you do not keep serving a possibly-broken build until the next restart,
relaunch through the new script now (it rebuilds the artifacts if they are
missing). This no-ops unless a dashboard session is actually running and the new
script has arrived on disk:

```bash
if [ -x ~/agent/skills/dashboard/scripts/serve ] && screen -ls | grep -q '\.dashboard[[:space:]]'; then
  screen -S dashboard -X quit 2>/dev/null
  screen -dmS dashboard ~/agent/skills/dashboard/scripts/serve
fi
```

### 3. Mark this migration applied

Call `mark_migration_applied` with `name="2026-07-dashboard-self-heal"`.
