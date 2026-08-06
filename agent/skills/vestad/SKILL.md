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

This skill's helpers are commands: `register-service`, `service-key`, `user-notification`, and
`vestad-health`. Agent startup links every executable in this skill's `scripts/` directory onto
`PATH` under its filename, so a full path like
`~/agent/skills/vestad/scripts/register-service` runs exactly the same script. These four helpers
are the only commands startup links; every other skill puts its own command on PATH from its own
setup: `uv tool install --editable <skill>/cli` for a `cli/` project, or
`ln -sf ~/agent/skills/<skill>/<skill> ~/.local/bin/<skill>` for a single launcher.

Restarting or stopping this agent is not a curl: use the `restart_vesta` / `stop_vesta`
tools, which call vestad's self-scoped lifecycle endpoints.

## Health check (is vestad up?)

Run `vestad-health` (add `-q` for exit-code only). It prints
`UP` / `DOWN <code>`. Use this instead of hand-typing a curl: vestad is HTTPS with a
self-signed cert and the path is `/agents/$AGENT_NAME/services`, so a plain
`http://127.0.0.1:$VESTAD_PORT/services` returns `000` unconditionally and mimics an
outage (that misread cost a 9-hour phantom "vestad down", 2026-07-14). Before ever
concluding vestad is down, run the helper; a `000` from a hand-typed http call is your
bug, not an outage. The local config/provider API is a separate thing: plain http on
`$WS_PORT`, not this.

## Services (get a port, keep it alive)

A service is a port inside the container that vestad reverse-proxies, either public (loads
through the tunnel with no credential at all) or private (gated by vestad, which accepts the api
key, an access token, or a service key minted for that service). Bind it to `0.0.0.0`: vestad
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
PORT=$(register-service tasks)
# public service: loads with no credential at all
PORT=$(register-service file-host --public)
```

The dashboard is private, and the app reaches it with a minted service key, so pass `--public`
only for something that must load with no credential at all, like a QR link a stranger's phone
opens or a webhook an external service posts to.

## Every skill command: the output contract

stdout carries only a command's successful output. A command that cannot do its job exits
non-zero and prints its failure on stderr, in the same shape it prints anything (a JSON
`{"error": ...}` envelope or plain text). That keeps a failure visible when stdout is piped
through `grep`, `head`, or `jq`, and makes an empty stdout with a non-zero exit mean "read
stderr". Inside a binary, route the choice through one helper that picks the stream from the
outcome rather than deciding at each print site. A command may document an exit code that is
itself an answer (`plex has` exits 0 found / 1 not; `vestad-health` reports `DOWN` for a gateway
it probed): a probe that determined the state has done its job and prints its answer on stdout.
Hold every command you write to this contract, and read failures from stderr when you script
around other commands. The daemon verbs below follow it.

## Giving a skill a daemon: the contract

A skill that runs a background process owns its whole lifecycle itself, in its own language,
behind one command, with the daemon as verbs on it: `<skill> daemon start|stop|restart|status`.
There is no shared runner, and no script path: a skill with a CLI adds a `daemon` subcommand, a
skill without one is a single executable at `~/agent/skills/<skill>/<skill>`, which you link onto
PATH from your setup (`ln -sf ~/agent/skills/<skill>/<skill> ~/.local/bin/<skill>`). A command you
just wrote runs by its path until you link it.

A skill's command is its directory name, always. A skill whose name would shadow a system command
names its directory to dodge the collision instead: the ssh tunnel lives in `ssh-tunnel/`, so its
command is `ssh-tunnel` and never `ssh`. A CLI installed as a uv console script is a separate
mechanism and can carry any name its project declares, which is why `voice-keys` (the `voice`
skill) and `finance` (the `enable-banking` skill) differ from their directory; each skill's own
docs name the command it installs, so read those rather than assuming.

Each verb prints exactly one line of JSON on stdout:

| verb | did the work | nothing to do |
| --- | --- | --- |
| `start` | `{"status":"started"}` | `{"status":"already_running"}` |
| `stop` | `{"status":"stopped"}` | `{"status":"already_stopped"}` |
| `restart` | `{"status":"started"}` | `{"status":"started"}` (a stopped daemon just starts) |
| `status` | `{"running":true,"port":8123}` | `{"running":false,"port":null}` |

A verb that cannot do its job prints `{"error":"<what went wrong>"}` on **stderr** and exits
non-zero. `port` is `null` for a daemon that serves no port. The command with no arguments and
the help forms (`-h`, `--help`, `help`, and `daemon help`) print usage on stdout and exit 0, so a
command the agent reaches for blind answers instead of failing.

State lives in the same three places for every skill, under one name the daemon picks for itself
(normally its command, `voice-keys` calling its daemon `voice`):

- pid: `~/agent/data/daemons/<name>.pid`, port: `~/agent/data/daemons/<name>.port`
  The pid record is **`<pid> <starttime>`**, two space-separated fields, where starttime is
  field 22 of `/proc/<pid>/stat` (clock ticks since boot). A pid alone answers "does some
  process hold this number"; the pair answers "is this still the process I started", which is
  the question status actually needs. A daemon writes the bare pid when `/proc` is unreadable,
  and a reader treats a bare pid as trusted rather than as a mismatch, so records written by
  older code keep working. Anything writing this file must write both fields when it can.
- log: `~/agent/logs/<name>.log`, appended, never truncated
- budgets: `DAEMON_READY_TIMEOUT_SECS` bounds a start (default 30, and 300 for whatsapp and
  telegram, which compile their CLI on the way up), `DAEMON_STOP_TIMEOUT_SECS` bounds a stop
  (default 15)

Boot empties the records directory before any daemon runs, because a pid written by the previous
container can already belong to something else in the fresh pid space, which would read as live
and turn the next start into a silent no-op. That clears records across a restart; the recorded
starttime is what protects a record whose daemon died mid-life, which boot never sees.

Six properties, which are what make a restart file a plain list of starts:

- **start is idempotent**: a recorded pid that is still alive answers `already_running` and
  spawns nothing, so re-running a start can never stack a second copy.
- **start is exclusive**: the pid record is claimed with an exclusive create (the parent's own
  pid) before anything is registered or spawned, so a start that loses that race answers
  `already_running` instead of stacking a second daemon beside the winner's. A loser has three
  ways out: a record naming a live process is `already_running`, touching nothing; a record no
  process stands behind is cleared and taken over, which is the one path on which two starts can
  both spawn, and the duplicate loses on its own port or socket; a record it cannot take over is
  the failure envelope `another <skill> start holds ...`.
- **start returns ready**: `started` means the daemon is up, a port-serving one answering on its
  port, so the caller's next line can use it. `already_running` means a start owns the daemon,
  which may still be inside its own ready wait.
- **start fails closed**: a registration that fails launches nothing, and a launch that never
  becomes ready is killed and both records removed before the error, because a daemon that is
  alive and unreachable would read as running and make every later start decline.
- **stop is SIGTERM then SIGKILL** to the recorded pid, both inside the one
  `DAEMON_STOP_TIMEOUT_SECS` budget: SIGTERM is the exit the agent asked for, and a daemon that
  has not honoured it two thirds of the way through the budget is killed, with the remainder left
  to reap it. So a stop either ends the daemon or fails loudly having left it standing, and
  `restart_vesta` is what recovers that. telegram signals the process group rather than the pid,
  because a watchdog signalled alone leaves the `telegram daemon start` it is running mid-restart
  to bring back what the stop just ended, and its stop ends two processes (watchdog first) sharing
  that one budget. whatsapp is the one deliberate exception, reporting a daemon that will not go
  rather than killing it, since a SIGKILL mid history sync risks having to pair the phone again.
- **status is a local read** of those two records, never a call to vestad, so it answers
  instantly and truthfully while vestad is down.

Two obligations that are easy to miss:

- **A daemon that serves a port registers it itself**, inside start, before launching, and passes
  the port to the process. Register private (no `--public`) unless the service is a page that
  must load with no credential at all; a private service is reached with a minted service key.
- **A daemon that writes a `daemon_died` notification recognizes SIGTERM in-process** and stays
  silent for it, so a deliberate stop is never reported as a crash. Every other way out is
  reported, since nothing else notices a daemon that quietly went away.

The contract has one exemplar per language, each a real launcher this repo's conformance
tests hold to the behavior above: shell is `~/agent/skills/file-host/file-host`, Python is
`~/agent/skills/tasks/cli/src/tasks_cli/daemon.py`, and Go is
`~/agent/skills/whatsapp/cli/daemon.go`. Read the one in the language you are writing in
and follow it.

Then add the startup line yourself, inside the fenced block in the `## Daemons` section of
`~/agent/skills/restart/SKILL.md`, so the daemon comes back after a container restart. It is the
bare command, nothing around it, because start is idempotent:

```bash
file-host daemon start
```

vestad's API may still be coming up when that block runs, so `register-service` polls until
vestad answers (up to `REGISTER_SERVICE_WAIT` seconds, default 30) and, if it never does, exits
non-zero with a stderr message and no port. A start treats that as fatal and launches nothing,
because a daemon on a port vestad does not know about is worse than one that did not start.

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

The `service-key` helper does the curl. `mint` prints the secret alone, because vestad shows
it exactly once, so put it straight into the link:

```bash
KEY=$(service-key mint expenses --label accountant)
echo "$VESTAD_TUNNEL/agents/$AGENT_NAME/expenses/k/$KEY/"
```

Add `--ttl <secs>` for a shorter life than the 30 day default, or `--never-expires` for a
long-lived consumer. List the live keys (ids and labels only, never the secrets) and revoke
one by id:

```bash
service-key list expenses
service-key revoke expenses <id>
```

Minting fails loudly rather than printing an empty key: if the service is not registered,
the helper says so and exits non-zero, so register it first.

## Public URLs (how to reach a service from outside)

vestad exposes registered services under the tunnel. The stable patterns:
- **Skill/service routes**: `$VESTAD_TUNNEL/agents/$AGENT_NAME/<service>/...`. A service registered `public: true` needs no credential. A private one is gated by vestad, which accepts the app's api key or a service key minted for that service, carried as an `Authorization: Bearer <key>` header, a `?token=<key>` query param, or a `/k/<key>/` prefix right after the service name. `X-Agent-Token` is not a credential here: the proxy never accepts it, so a curl that only sets that header gets a 401. A dashboard registered as service `dashboard` is at `$VESTAD_TUNNEL/agents/$AGENT_NAME/dashboard/`, and a link someone else can open is `$VESTAD_TUNNEL/agents/$AGENT_NAME/dashboard/k/<key>/`. Prefer the path form for anything a browser loads: a page's relative assets inherit the prefix, while a header or a query param reaches only the first request. Reach for the `?token=` form when the client cannot send a header at all, which in practice means a media element's `src` or a browser `WebSocket`. The voice service's audio stream and STT socket URLs carry their service key that way for that reason.
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
