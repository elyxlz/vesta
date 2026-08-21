# Dashboard setup

`node` and `npm` ship in the base image. Setup is two steps: a script, then one edit you make.

1. Run the setup script; it links `dashboard` onto PATH, installs deps, builds, starts the daemon, and confirms a 200, all idempotent (safe to re-run):
   ```bash
   ~/agent/skills/dashboard/scripts/setup.sh
   ```
   It fails loudly on a real problem rather than leaving a half-set-up dashboard: check its output, don't assume success.

2. **Register the restart line yourself**, so the dashboard survives a container restart. Register this line for restart as `~/agent/skills/restart/SKILL.md` describes:
   ```
   dashboard daemon start
   ```
   Skip this and the dashboard is up now but gone after the next restart.

## Manual steps (only if setup.sh can't be used)

These replace step 1 above; step 2 stays yours either way.

1. **Install dependencies**: `cd ~/agent/skills/dashboard/app && npm install`
2. **Build**: `cd ~/agent/skills/dashboard/app && npx vite build`
3. **Start the daemon**: `dashboard daemon start`. Manage it with `daemon start|stop|restart|status`. Start is idempotent and never stacks a duplicate.
4. **Check it's alive**: `dashboard daemon status` reports `running` and the `port` it serves on; fetch that port to confirm it answers.
