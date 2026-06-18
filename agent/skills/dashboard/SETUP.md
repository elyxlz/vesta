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

Register with vestad to get a port (see [service](../service/SKILL.md)), then start the server:
```bash
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public)
screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```

## 4. Register the service

Add this startup command to the `## Services` section of `~/agent/skills/restart/SKILL.md`:
```
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public) && screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```
