# Dashboard setup

`node` and `npm` ship in the base image. Setup is two steps: a script, then one edit you make.

1. Run the setup script; it installs deps, builds, starts the daemon, and confirms a 200, all idempotent (safe to re-run):
   ```bash
   ~/agent/skills/dashboard/scripts/setup.sh
   ```
   It fails loudly on a real problem rather than leaving a half-set-up dashboard: check its output, don't assume success.

2. **Register the restart line yourself**, so the dashboard survives a container restart. Add this line inside the fenced block in the `## Daemons` section of `~/agent/skills/restart/SKILL.md`, matching the guard form already there:
   ```
   running dashboard || { ~/agent/skills/dashboard/scripts/daemon start; sleep 1; }
   ```
   Skip this and the dashboard is up now but gone after the next restart.

## Manual steps (only if setup.sh can't be used)

These replace step 1 above; step 2 stays yours either way.

1. **Install dependencies**: `cd ~/agent/skills/dashboard/app && npm install`
2. **Build**: `cd ~/agent/skills/dashboard/app && npx vite build`
3. **Start the daemon**: `~/agent/skills/dashboard/scripts/daemon start` (idempotent, never stacks a duplicate)
4. **Check it's alive**: `~/agent/skills/dashboard/scripts/daemon status` reports `running`, `port`, and `http_ok` in one JSON blob.
