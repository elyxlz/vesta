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

Register with vestad to get a port, then start the server:
```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"dashboard","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```

## 4. Register the service

Add to the `## Services` section of `~/agent/skills/restart/SKILL.md`:
```
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"dashboard","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS dashboard sh -c "cd ~/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```
