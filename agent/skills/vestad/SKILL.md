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

`$VESTAD_PORT`, `$AGENT_TOKEN`, `$AGENT_NAME`, `$VESTAD_TUNNEL`, and `$BOX_HOST` come
from `/run/vestad-env`, already exported into the environment. The API is
`https://$BOX_HOST:$VESTAD_PORT`, with a self-signed cert, so always `curl -sk`.

Restarting or stopping this agent is not a curl: use the `restart_vesta` / `stop_vesta`
tools, which call vestad's self-scoped lifecycle endpoints.

## Health check (is vestad up?)

Run `~/agent/skills/vestad/scripts/health` (add `-q` for exit-code only). It prints
`UP` / `DOWN <code>`. Use this instead of hand-typing a curl: vestad is HTTPS with a
self-signed cert and the path is `/agents/$AGENT_NAME/services`, so a plain
`http://127.0.0.1:$VESTAD_PORT/services` returns `000` unconditionally and mimics an
outage (that misread cost a 9-hour phantom "vestad down", 2026-07-14). Before ever
concluding vestad is down, run the helper; a `000` from a hand-typed http call is your
bug, not an outage. The local config/provider API is a separate thing: plain http on
`$WS_PORT`, not this.

## Services (get a port, keep it alive)

A service is a port inside the container that vestad reverse-proxies, optionally public
(reachable through the tunnel without a token) or token-gated. Bind it to `0.0.0.0`: vestad
reaches it over this container's network, so a `127.0.0.1` bind is invisible to the proxy even
with the port registered correctly. Register one when something outside the process needs to
reach it: a web UI, an inbound webhook, an API the app calls.
A background process that needs no inbound port is just a daemon: it does not register here,
it only goes in the restart skill's `## Daemons` section.

Skills that run a service register it with vestad to get a port, then start it. The
`register-service` helper does the curl and prints the port (idempotent: same port per name, so
a re-register that only wants the port is safe). Exposure is sent on every call, so a service
registered without `--public` is private:

```bash
# private service: the api key or a minted service key reaches it
PORT=$(~/agent/skills/vestad/scripts/register-service tasks)
# public service: loads with no credential at all
PORT=$(~/agent/skills/vestad/scripts/register-service file-host --public)
```

The dashboard is private, and the app reaches it with a minted service key, so pass `--public`
only for something that must load with no credential at all, like a QR link a stranger's phone
opens or a webhook an external service posts to.

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

List registrations, unregister a service, or tell connected clients to reload after changing
what a service serves:

```bash
curl -sk https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X DELETE https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services/<name> -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X POST https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services/<name>/invalidate -H "X-Agent-Token: $AGENT_TOKEN"
```

Invalidate optionally takes `{"scope": "<part>"}` (e.g. `{"scope": "stt"}`) to mark what
changed; omit the body for a full invalidation.

## Share a private service (mint a service key)

vestad is the only gate in front of a private service, and a service key is the credential
that opens one without handing out the app's api key. A key is scoped to one service on one
agent, is stored only as a hash, expires in 30 days by default, and can be revoked at any
time. Mint one when someone or something that has no Vesta login needs to reach a service:

```bash
BASE=https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services
curl -sk -X POST "$BASE/<service>/keys" -H "X-Agent-Token: $AGENT_TOKEN" \
  -H 'Content-Type: application/json' -d '{"label": "who it is for", "ttl_secs": 604800}'
```

It returns `{"id": ..., "key": ..., "expires_at": ...}`; the `key` is shown exactly once, so
put it straight into the link. Omit `ttl_secs` for the default, or pass
`{"never_expires": true}` for a long-lived consumer. List the live keys with a `GET` on the
same path (ids and labels only, never the secrets), and revoke one by id:

```bash
curl -sk "$BASE/<service>/keys" -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X DELETE "$BASE/<service>/keys/<id>" -H "X-Agent-Token: $AGENT_TOKEN"
```

## Public URLs (how to reach a service from outside)

vestad exposes registered services under the tunnel. The stable patterns:
- **Skill/service routes**: `$VESTAD_TUNNEL/agents/$AGENT_NAME/<service>/...`. A service registered `public: true` needs no credential. A private one is gated by vestad, which accepts the app's api key or a service key minted for that service, carried as an `Authorization: Bearer <key>` header, a `?token=<key>` query param, or a `/k/<key>/` prefix right after the service name. `X-Agent-Token` is not a credential here: the proxy never accepts it, so a curl that only sets that header gets a 401. A dashboard registered as service `dashboard` is at `$VESTAD_TUNNEL/agents/$AGENT_NAME/dashboard/`, and a link someone else can open is `$VESTAD_TUNNEL/agents/$AGENT_NAME/dashboard/k/<key>/`. Prefer the path form for anything a browser loads: a page's relative assets inherit the prefix, while a header or a query param reaches only the first request.
- **User-facing web app**: `$VESTAD_TUNNEL/app`.

Reach for these instead of reverse-engineering the route when you need to hand the user a link.

## Update vestad

Check the running version and whether a newer release exists, then apply it:

```bash
curl -sk https://$BOX_HOST:$VESTAD_PORT/version -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X POST https://$BOX_HOST:$VESTAD_PORT/gateway/update -H "X-Agent-Token: $AGENT_TOKEN"
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
curl -sk "https://$BOX_HOST:$VESTAD_PORT/gateway/logs?tail=200" -H "X-Agent-Token: $AGENT_TOKEN"
```

Returns the last N lines as Server-Sent Events, so parse the `data:` lines; it closes after
the tail. Add `&follow=true` to keep streaming live.
