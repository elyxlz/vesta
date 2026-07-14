---
name: vestad
description: Talk to vestad, the host daemon that runs this container. Register a background service to get a port, build public URLs, update vestad to the latest release, check its version, and read gateway logs. Use when a skill needs an inbound port or a shareable link, when the user asks to update Vesta, or when debugging gateway/container issues.
---

# vestad (the host daemon)

vestad is the Rust daemon on the host that owns this container: it creates, rebuilds,
starts, and stops agents, proxies app/CLI traffic, and serves the HTTP API used below.
Every call authenticates with the agent's own token:

```bash
-H "X-Agent-Token: $AGENT_TOKEN"
```

`$VESTAD_PORT`, `$AGENT_TOKEN`, `$AGENT_NAME`, and `$VESTAD_TUNNEL` come from
`/run/vestad-env`, already exported into the environment. The API is
`https://localhost:$VESTAD_PORT` (self-signed cert, so always `curl -sk`).

Restarting or stopping this agent is not a curl: use the `restart_vesta` / `stop_vesta`
tools, which call vestad's self-scoped lifecycle endpoints.

## Services (get a port, keep it alive)

A service is a port inside the container that vestad reverse-proxies, optionally public
(reachable through the tunnel without a token) or token-gated. Register one when something
outside the process needs to reach it: a web UI, an inbound webhook, an API the app calls.
A background process that needs no inbound port is just a daemon: it does not register here,
it only goes in the restart skill's `## Daemons` section.

Skills that run a service register it with vestad to get a port, then start it. The
`register-service` helper does the curl and prints the port (idempotent: same port per name):

```bash
# token-only service
PORT=$(~/agent/skills/vestad/scripts/register-service tasks)
# public service (reachable through the tunnel without a token)
PORT=$(~/agent/skills/vestad/scripts/register-service dashboard --public)
```

So the service comes back after a container restart, add its startup command to the
`## Daemons` section of `~/agent/skills/restart/SKILL.md`, one fenced block per skill. Use a
single line that re-registers and starts, e.g.:

```bash
running tasks || { PORT=$(~/agent/skills/vestad/scripts/register-service tasks) && screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications --port $PORT; sleep 1; }
```

vestad's API may still be coming up when the daemon block runs, so `register-service` polls
until vestad answers (up to `REGISTER_SERVICE_WAIT` seconds, default 30) and, if it never does,
exits non-zero with a stderr message and no port. Keep the `&&` between registration and start:
a failed registration short-circuits the chain, so the daemon never launches portless. Wrap the
whole line in the `running <name> ||` guard the Daemons block defines, so re-running it (crash
recovery re-enters the block) never stacks a duplicate daemon.

List registrations, or tell connected clients to reload after changing what a service serves:

```bash
curl -sk https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services/<name>/invalidate -H "X-Agent-Token: $AGENT_TOKEN"
```

Invalidate optionally takes `{"scope": "<part>"}` (e.g. `{"scope": "stt"}`) to mark what
changed; omit the body for a full invalidation.

## Public URLs (how to reach a service from outside)

vestad exposes registered services under the tunnel. The stable patterns:
- **Skill/service routes**: `$VESTAD_TUNNEL/agents/$AGENT_NAME/<service>/...` (a service registered `public: true` needs no auth; otherwise pass `X-Agent-Token`). A dashboard registered as service `dashboard` is at `$VESTAD_TUNNEL/agents/$AGENT_NAME/dashboard/`.
- **User-facing web app**: `$VESTAD_TUNNEL/app`.

Reach for these instead of reverse-engineering the route when you need to hand the user a link.

## Update vestad

Check the running version and whether a newer release exists, then apply it:

```bash
curl -sk https://localhost:$VESTAD_PORT/version -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X POST https://localhost:$VESTAD_PORT/gateway/update -H "X-Agent-Token: $AGENT_TOKEN"
```

`GET /version` returns `{version, latest_version, update_available, channel, ...}` from a
periodic release check; `POST /version/check` forces a fresh check first. An update is
host-global: vestad replaces itself, restarts, and in doing so stops and restarts every
agent on the host, this one included. Expect the update call's response to never arrive
when it succeeds; the container simply comes back on the new version, like `restart_vesta`.
Only run it when the user asks or has standing approval. On a dev-mode vestad the endpoint
returns 400 (self-update disabled).

## Gateway logs (self-diagnosis)

Read vestad's own logs to debug gateway or container issues:

```bash
curl -sk "https://localhost:$VESTAD_PORT/gateway/logs?tail=200" -H "X-Agent-Token: $AGENT_TOKEN"
```

Returns the last N lines as Server-Sent Events, so parse the `data:` lines; it closes after
the tail. Add `&follow=true` to keep streaming live.
