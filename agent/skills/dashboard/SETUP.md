# Dashboard setup

## 1. Install dependencies

```bash
which node || (curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs)
cd ~/vesta/skills/dashboard/app && npm install
```

## 2. Build the dashboard

```bash
cd ~/vesta/skills/dashboard/app && npx vite build
```

## 3. Start the dashboard server

Pick a free port (e.g. 7966). Start the server in a background screen session:
```bash
SKILL_PORT=7966 screen -dmS dashboard sh -c 'cd ~/vesta/skills/dashboard/app && npx vite preview --port 7966 --host 0.0.0.0'
```

## 4. Register with vestad

Register the service with vestad so it's reachable from outside the container:
```bash
curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H 'Content-Type: application/json' -d '{"name":"dashboard","port":7966}'
```
This persists across restarts — only needs to be done once.

## 5. Add to restart.md

Add to `~/vesta/prompts/restart.md`:
```
SKILL_PORT=7966 screen -dmS dashboard sh -c 'cd ~/vesta/skills/dashboard/app && npx vite preview --port 7966 --host 0.0.0.0'
```
