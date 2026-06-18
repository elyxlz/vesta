---
name: service
description: Register a background daemon with vestad to get a port, and keep it alive across restarts. Use when a skill runs a long-lived serve process (dashboard, tasks, voice, webhook receivers).
---

# Service Registration

Skills that run a daemon register it with vestad to get a port, then start it. The
`register-service` helper does the curl and prints the port (idempotent: same port per name):

```bash
# token-only service
PORT=$(~/agent/skills/service/scripts/register-service tasks)
# public service (reachable through the tunnel without a token)
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public)
```

So the service comes back after a container restart, add its startup command to the
`## Services` section of `~/agent/skills/restart/SKILL.md`, one fenced block per skill. Use a
single line that re-registers and starts, e.g.:

```bash
PORT=$(~/agent/skills/service/scripts/register-service tasks) && screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications --port $PORT
```
