---
name: context
description: Use when the user asks about "context window", "token usage", "how much context is left", or wants to monitor the agent's live context consumption. Exposes a vestad-registered HTTP service that reads the SDK-authoritative `get_context_usage()` values logged by core/client.py, and ships a dashboard page that visualizes them.
---

# Context

Live context window usage for the agent, surfaced as an HTTP endpoint and a dashboard page.

## Architecture

```
core/client.py  ── calls state.client.get_context_usage() every message cycle
                ── logs "[USAGE] Context: X% (Y/Z tokens)" to ~/agent/logs/vesta.log
                     │
                     ▼
server.py       ── tails vesta.log, parses the latest [USAGE] line
                ── samples to ~/agent/logs/context-status.jsonl every minute
                ── serves GET /  →  {percentage, tokens, max_tokens, nap_status,
                                      next_threshold, uptime, history}
                     │
                     ▼
dashboard       ── pages/agent.tsx polls apiFetch("context") every 30s
                ── renders percentage, status, uptime, progress, history bar chart
```

The server never re-computes usage. It reads the SDK's own answer off the log. If core is updated to change the log format, update `USAGE_RE` in `server.py`.

## Endpoint

Registered with vestad as `context` (public). Dashboard resolves the URL via `apiFetch("context")`.

Response shape:

```json
{
  "percentage": 28.0,
  "tokens": 282958,
  "max_tokens": 1000000,
  "nap_status": "ok",
  "next_threshold": "soft @ 50%",
  "uptime": "23m 12s",
  "history": [{"time": "20:11", "percentage": 22.78}, ...]
}
```

Thresholds are hardcoded in `server.py`: soft 50%, hard 70%. `nap_status` is `ok` / `warning` / `critical`.

## Dashboard integration

The dashboard page lives at `dashboard/page.tsx`. To install it into the dashboard skill:

1. Symlink (or copy) `dashboard/page.tsx` into `~/agent/skills/dashboard/app/src/pages/agent.tsx`.
2. Add an entry to `config.tsx`:

```tsx
import { BrainIcon } from "lucide-react"
import AgentPage from "./pages/agent"

{ id: "agent", title: "Agent", icon: <BrainIcon className="size-4" />, component: AgentPage }
```

3. Rebuild: `cd ~/agent/skills/dashboard/app && npx vite build`, restart the dashboard screen, and `POST .../services/dashboard/invalidate`.

Current install uses a symlink:
`~/agent/skills/dashboard/app/src/pages/agent.tsx → ~/agent/skills/context/dashboard/page.tsx`

## Running

Server startup lives in `restart.md`:

```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"context","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
SKILL_PORT=$PORT screen -dmS context-server /usr/bin/python3 /root/agent/skills/context/server.py
```

## Files

- `server.py`: the HTTP service
- `dashboard/page.tsx`: dashboard page component (symlinked into dashboard skill)
- Log sink: `~/agent/logs/context-status.jsonl` (trimmed to last 500 samples)
