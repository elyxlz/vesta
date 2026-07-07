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

## 3. Start the dashboard server

`scripts/serve` registers the service port (see [service](../service/SKILL.md)) and starts the preview, rebuilding `node_modules`/`dist` first if they are missing. Start it, and fetch the port for the check below:
```bash
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public)
screen -dmS dashboard ~/agent/skills/dashboard/scripts/serve
```

## 4. Register the service

Add this guarded startup command to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
```
running dashboard || { screen -dmS dashboard ~/agent/skills/dashboard/scripts/serve; sleep 1; }
```

## 5. Check it's alive

The build and server run in the background, so confirm the dashboard is actually serving before considering it done, e.g. `curl -fsS localhost:$PORT >/dev/null`. Don't assume success; a failed build or server won't tell you.
