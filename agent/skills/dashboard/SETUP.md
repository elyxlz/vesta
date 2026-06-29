# Dashboard setup

## 1. Install dependencies

`node` and `npm` ship in the base image.

```bash
cd ~/agent/skills/dashboard/app && npm install
```

## 2. Build the dashboard

```bash
cd ~/agent/skills/dashboard/app && npx vite build
```

> **Run install and build in the FOREGROUND and confirm each succeeded before moving on — do NOT
> background them.** Only the preview *server* in step 3 is long-running and backgrounded; install
> and build are one-shot. A backgrounded build hides its failure: a missing dependency or broken
> import fails silently and you carry on thinking the dashboard is ready when `dist/` is stale or
> absent. After building, confirm the command exited 0 and printed vite's `✓ built in …` and that
> `dist/` exists. If it failed, fix the cause (e.g. install a missing package) and rebuild — never
> register or report the dashboard ready off an unverified build.

## 3. Start the dashboard server

Register with vestad to get a port (see [service](../service/SKILL.md)), then start the server:
```bash
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public)
screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```

## 4. Register the service

Add this startup command to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
```
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public) && screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```
