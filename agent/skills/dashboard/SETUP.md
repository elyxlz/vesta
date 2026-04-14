# Dashboard setup

## 1. Install dependencies

```bash
which node || (curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs)
cd ~/vesta/agent/skills/dashboard/app && npm install
```

## 2. Build the dashboard

```bash
cd ~/vesta/agent/skills/dashboard/app && npx vite build
```

## 3. Start the dashboard server

Register with vestad to get a port, then start the server:
```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"dashboard","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -dmS dashboard sh -c "cd ~/vesta/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```

## 4. Add to restart.md

Add to `~/vesta/agent/prompts/restart.md`:
```
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"dashboard","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS dashboard sh -c "cd ~/vesta/agent/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```
