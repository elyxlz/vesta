# Handover: let the user sign in on the agent's browser

**This is the primary fallback when stealth is not enough.** Some sites (Google sign-in,
banking, locked tenants) gate on account trust, not fingerprint, and want a human once. Hand the
live headed browser to the user over a clean, Vesta-branded page and let them sign in by hand.
Whatever they sign into persists in the shared profile, so the agent's everyday browser grows
more trusted over time, like a real user's.

```bash
browser handover start --url "https://accounts.google.com" --port <service-port>
browser handover status
browser handover stop
```

## How it works

`handover start` launches headed Camoufox on the shared profile under an X server (Xvfb +
openbox), then bridges it out with `x11vnc` + `websockify` serving a branded noVNC page. It
returns the page path to send the user. `handover stop` tears the whole thing down; `status`
reports what is up.

The public URL is the caller's job: register a `--public` vestad service to get a port, pass it
as `--port`, and hand the user `$VESTAD_TUNNEL/agents/$AGENT_NAME/<service>/handover.html`.
vestad proxies the websocket through that route, so the same page works for a remote user with no
extra tunnel.

## Talking to the user

The page is deliberately generic (it says only "Vesta's browser"); you tell the user the task in
chat. Point them at the URL, tell them exactly what to sign into, and wait. When they are done,
`browser handover stop`, then resume automating on the same shared profile: the fresh session
cookies are already there.

## Requirements

Needs the handover binaries: `apt-get install -y novnc x11vnc openbox xdotool scrot` (see
SETUP.md). If they are missing, `handover start` fails with an install hint.
