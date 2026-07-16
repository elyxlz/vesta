# Dashboard setup

`node` and `npm` ship in the base image. Run the one-shot setup script; it installs
deps, builds, starts the daemon, confirms a 200, and appends the guarded startup line
to the restart skill, all idempotent (safe to re-run):
```bash
~/agent/skills/dashboard/scripts/setup.sh
```

It fails loudly on a real problem rather than leaving a half-set-up dashboard: check its output, don't assume success.

## Manual steps (only if setup.sh can't be used)

1. **Install dependencies**: `cd ~/agent/skills/dashboard/app && npm install`
2. **Build**: `cd ~/agent/skills/dashboard/app && npx vite build`
3. **Start the daemon**: `~/agent/skills/dashboard/scripts/daemon start` (idempotent, never stacks a duplicate)
4. **Register the restart line**: add this guarded startup command to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
   ```
   running dashboard || { ~/agent/skills/dashboard/scripts/daemon start; sleep 1; }
   ```
5. **Check it's alive**: `~/agent/skills/dashboard/scripts/daemon status` reports `running`, `port`, and `http_ok` in one JSON blob.
