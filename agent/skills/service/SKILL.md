---
name: service
description: Register a background daemon with vestad to get a port, and keep it alive across restarts. Use when a skill runs a long-lived serve process (dashboard, tasks, voice, webhook receivers).
---

# Service Registration

A service is a port inside the container that vestad reverse-proxies, optionally public
(reachable through the tunnel without a token) or token-gated. Register one when something
outside the process needs to reach it: a web UI, an inbound webhook, an API the app calls.
A background process that needs no inbound port is just a daemon: it does not register here,
it only goes in the restart skill's `## Daemons` section.

Skills that run a service register it with vestad to get a port, then start it. The
`register-service` helper does the curl and prints the port (idempotent: same port per name):

```bash
# token-only service
PORT=$(~/agent/skills/service/scripts/register-service tasks)
# public service (reachable through the tunnel without a token)
PORT=$(~/agent/skills/service/scripts/register-service dashboard --public)
```

So the service comes back after a container restart, add its startup command to the
`## Daemons` section of `~/agent/skills/restart/SKILL.md`, one fenced block per skill. Use a
single line that re-registers and starts, e.g.:

```bash
PORT=$(~/agent/skills/service/scripts/register-service tasks) && screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications --port $PORT
```

vestad's API may still be coming up when the daemon block runs, so `register-service` polls
until vestad answers (up to `REGISTER_SERVICE_WAIT` seconds, default 30) and, if it never does,
exits non-zero with a stderr message and no port. Keep the `&&` between registration and start:
a failed registration short-circuits the chain, so the daemon never launches portless.
