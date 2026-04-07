# Dashboard setup

## 1. Install dependencies

```bash
which node || (curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs)
cd ~/vesta/skills/dashboard/app && npm install
```

## 2. Sync shared files from the main app

The dashboard shares UI components, styles, and utilities with the main Vesta app. Run the sync script to download them:
```bash
bash ~/vesta/skills/dashboard/sync-app.sh
```

This fetches `globals.css`, `components/ui/`, `lib/utils.ts`, and `hooks/use-mobile.ts` from the main app (GitHub, pinned to the current version). Run this again after upstream updates to keep the dashboard visually in sync.

## 3. Build the dashboard

```bash
cd ~/vesta/skills/dashboard/app && npx vite build
```

## 4. Start the dashboard server

Register with vestad to get a port, then start the server:
```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```

## 5. Add to restart.md

Add to `~/vesta/prompts/restart.md`:
```
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H 'Content-Type: application/json' -d '{"name":"dashboard"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS dashboard sh -c "cd ~/vesta/skills/dashboard/app && npx vite preview --port $PORT --host 0.0.0.0"
```
