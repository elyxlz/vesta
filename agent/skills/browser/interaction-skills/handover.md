# Handover: let the user sign in on the agent's browser

**This is the primary fallback when stealth is not enough.** Some sites (Google sign-in,
banking, locked tenants) gate on account trust, not fingerprint, and want a human once. Hand the
live headed browser to the user over a clean, Vesta-branded page and let them sign in by hand.
Whatever they sign into persists in the shared profile, so the agent's everyday browser grows
more trusted over time, like a real user's.

```bash
browser handover start --url "https://accounts.google.com"
browser handover status
browser handover stop
```

## How it works

`handover start` launches headed Camoufox on the shared profile under an X server (Xvfb +
openbox), then bridges it out with `x11vnc` + `websockify` serving a branded noVNC page. `handover
stop` tears the whole thing down, including the public vestad registration; `status` reports what is
up.

**The registration is part of the teardown, not tidiness.** `start` registers a PUBLIC route, and a
route that outlives its session advertises a public path at a port nothing is listening on, which the
next handover then inherits without having created it. A handover is by definition an authenticated
session on something the user cares about (bank, airline, email), so the route must die with it.

**`stopped: true` is a claim about the teardown, so confirm it the same way you would any other**:
the registry no longer lists `browser`, nothing is listening on the port, and `pgrep -x camoufox`
returns 0. If a session was killed without `stop` ever running, remove the leftover by hand:

```bash
~/agent/skills/vestad/scripts/deregister-service browser
```

On a box, `start` registers a public vestad service itself and returns the ready-to-send
`user_url` (`$VESTAD_PUBLIC_URL/agents/$AGENT_NAME/browser/handover.html`); vestad proxies the
websocket through that route, so the same page works for a remote user with no extra tunnel. Off a
box (dev), it returns a `http://localhost:<port>/handover.html` link instead. Pass `--port` only
to override the port by hand.

## Talking to the user

The page is deliberately generic (it says only "Vesta's browser"); you tell the user the task in
chat. Send them the returned `user_url`, tell them exactly what to sign into, and wait. When they
are done, `browser handover stop`, then resume automating on the same shared profile: the fresh
session cookies are already there.

## Requirements

Needs the handover binaries: `apt-get install -y xvfb novnc x11vnc openbox` (see SETUP.md).
`browser doctor` reports whether they are present; if any are missing, `handover start` fails with
an install hint.
