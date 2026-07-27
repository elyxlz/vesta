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

## Giving a skill a daemon

Every skill that runs a background process exposes the same four verbs,
`daemon start|stop|restart|status`, and delegates the behavior to one shared runner,
`~/agent/skills/vestad/scripts/daemon-lifecycle`. The runner owns the screen guard, port
registration, readiness polling, stopping the process, and the JSON status, so a skill declares
only what is its own:

| flag | meaning |
| --- | --- |
| `--session NAME` | the screen session; not always the skill name (`spotify` runs `spotify-watch`) |
| `--service NAME` | the name registered with vestad; not always the session name (`sign-service` registers as `sign`) |
| `--port-mode MODE` | `none` (default), `private`, or `public` |
| `--workdir DIR` | cd here before launching |
| `--probe MODE` | `none` (default), or `http` for a 200 on the registered port |
| `--stop-marker PATH` | written before stopping, so the daemon can tell a deliberate stop from a crash |
| `--pidfile PATH` | the daemon's own pid file, so stop signals the process and a live pid counts as running |
| `-- COMMAND ...` | what runs inside the session; it sees `$PORT` when a port was registered |

A skill with a CLI adds a `daemon` subcommand that shells the runner, so the agent types
`tasks daemon start`. A skill without one adds a `scripts/daemon` wrapper:

```sh
#!/bin/sh
set -eu
exec "$HOME/agent/skills/vestad/scripts/daemon-lifecycle" "$@" \
  --session file-host \
  --service file-host \
  --port-mode public \
  -- /bin/sh -c 'exec python3 ~/agent/skills/file-host/serve.py --port "$PORT"'
```

Two rules that are easy to miss:

- **A daemon that ignores SIGHUP must pass `--pidfile`.** Quitting a screen session only sends
  SIGHUP, so such a daemon outlives the quit, runs no shutdown path, and would read as stopped
  while still alive, letting the next start stack a second copy.
- **A daemon that writes a `daemon_died` notification must honor the stop marker**: check for it
  on shutdown, clear it, and stay silent, so a deliberate stop is not reported as a crash.

Then add the guarded startup line yourself, inside the single fenced block in the `## Daemons`
section of `~/agent/skills/restart/SKILL.md`, so the daemon comes back after a container restart:

```bash
running tasks || { tasks daemon start; sleep 1; }
```

`register-service` prints a port and is idempotent (same port per name, and re-registering
without `--public` keeps the service's current exposure rather than revoking it). The runner
calls it for you; call it directly only when you need a port outside a daemon:

```bash
PORT=$(~/agent/skills/vestad/scripts/register-service tasks)
PORT=$(~/agent/skills/vestad/scripts/register-service dashboard --public)
```

vestad's API may still be coming up when the daemon block runs, so `register-service` polls
until vestad answers (up to `REGISTER_SERVICE_WAIT` seconds, default 30) and, if it never does,
exits non-zero with a stderr message and no port. The runner treats that as fatal and does not
launch, because a daemon on a port vestad does not know about is worse than one that did not start.

List registrations, unregister a service (also how you make a public service private: drop the
registration, then register it again without `--public`), or tell connected clients to reload
after changing what a service serves:

```bash
curl -sk https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X DELETE https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services/<name> -H "X-Agent-Token: $AGENT_TOKEN"
curl -sk -X POST https://$BOX_HOST:$VESTAD_PORT/agents/$AGENT_NAME/services/<name>/invalidate -H "X-Agent-Token: $AGENT_TOKEN"
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
