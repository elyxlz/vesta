---
name: context
description: Use when the user asks about "context window", "token usage", "how much context is left", SDK response time / latency, or wants to monitor the agent's live context consumption and runtime activity. Exposes a vestad-registered HTTP service that reads the SDK-authoritative `get_context_usage()` values logged by `core/client.py`, plus USAGE / state / tool / message lines, and ships a dashboard page that visualizes them.
---

# Context

Live runtime observability for the agent: context window usage, SDK response times, nap control, a token-idle notification, and a brain-activity feed. Surfaced as an HTTP service and a dashboard page.

## Architecture

```
core/client.py  ── calls state.client.get_context_usage() every message cycle
                ── logs "[USAGE] Context: X% (Y/Z tokens)"
                ── logs "[USAGE] in=.. out=.. cache_read=.. | cost=$.. | duration=..s"
                ── logs THINKING / TOOL CALL / ASSISTANT / state transitions
                     │
                     ▼
server.py       ── tails vesta.log, parses the latest [USAGE] line
                ── samples context % to ~/agent/logs/context-status.jsonl every minute
                ── samples turn durations from USAGE lines for the perf view
                ── auto-triggers nap on hard threshold, or soft + user idle
                ── writes a user-idle notification when the user has been quiet
                     │
                     ▼
dashboard       ── agent page polls apiFetch("context") every 30s
                ── renders usage %, status, nap controls, audio check,
                   brain-activity feed, and a combined context % + SDK duration
                   5-min-bucket chart
```

The server never re-computes usage. It reads the SDK's own answer off the log. If core is updated to change the log format, update `USAGE_RE` in `server.py`.

## Endpoints

Registered with vestad as `context` (public). Dashboard resolves the URL via `apiFetch("context")`.

| Endpoint                    | Method | Returns                                                      |
|-----------------------------|--------|--------------------------------------------------------------|
| `/` or `/status`            | GET    | full snapshot: usage, status, uptime, history, timeseries, nap |
| `/config`                   | GET    | nap / idle-notify config                                     |
| `/config`                   | POST   | update config (subset of keys allowed)                       |
| `/nap`                      | POST   | manually trigger a nap                                       |
| `/activity?limit=N`         | GET    | last N parsed log events (thinking / tool / message / …)     |
| `/perf?limit=N`             | GET    | last N agent turns (in/out tokens, cache, cost, duration)    |

Response shape for `/`:

```json
{
  "percentage": 28.0,
  "tokens": 282958,
  "max_tokens": 1000000,
  "nap_status": "ok",
  "next_threshold": "soft @ 50%",
  "uptime": "23m 12s",
  "history": [{"time": "20:11", "percentage": 22.78, "duration_s": 15.3, "out_tok": 412}, ...],
  "timeseries": [{"time": "20:10", "pct": 22.78, "dur_min": 2.1, "dur_avg": 15.3, "dur_max": 48.2, "turn_count": 4}, ...],
  "nap": {
    "config": {"enabled": true, "soft_pct": 50, "hard_pct": 70, "idle_minutes": 5, "cooldown_minutes": 10, "user_idle_notify_minutes": 20},
    "idle_seconds": 12,
    "trigger_pending": false
  }
}
```

## Nap + user-idle

Two automatic behaviors:

1. **Nap trigger** — sampler loop fires `nap_request` when either:
   - `pct >= hard_pct` (default 70), or
   - `pct >= soft_pct` (default 50) AND user idle ≥ `idle_minutes` (default 5).

   Subject to `cooldown_minutes` (default 10). The `nap_request` file is consumed by core's `process_nap_request` loop, which queues the dream prompt.

2. **User-idle notification** — if `user_idle_notify_minutes > 0` (default 20) and the user has been idle that long, the server drops a passive (non-interrupting) notification to `~/agent/notifications/`. A 1-hour cooldown stamp stored at `~/agent/data/user_idle_last_notified_ts` prevents re-firing across service restarts.

## Uptime

The `uptime` field reads `ctime(/proc/1)` so it reflects the container's actual lifetime, not just the service's.

## Dashboard integration

`dashboard/page.tsx` is the reference page component. To install:

1. Copy or symlink it into the dashboard skill:
   `~/agent/skills/dashboard/app/src/pages/agent.tsx → ~/agent/skills/context/dashboard/page.tsx`
2. Register the page in `config.tsx`:
   ```tsx
   import { BrainIcon } from "lucide-react"
   import AgentPage from "./pages/agent"
   { id: "agent", title: "Agent", icon: <BrainIcon className="size-4" />, component: AgentPage }
   ```
3. Rebuild + restart the dashboard skill, and `POST .../services/dashboard/invalidate`.

## Running

Server startup lives in `restart.md`:

```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"context","public":true}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
SKILL_PORT=$PORT screen -dmS context-server /usr/bin/python3 ~/agent/skills/context/server.py
```

## Files

- `server.py` — the HTTP service (stdlib only)
- `dashboard/page.tsx` — dashboard page component
- Runtime data: `~/agent/logs/context-status.jsonl`, `~/agent/data/nap_request`, `~/agent/data/user_idle_last_notified_ts`
