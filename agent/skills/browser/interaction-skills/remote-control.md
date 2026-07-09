# Remote-control a browser you don't launch

**This is the last resort, below handover.** Prefer stealth (default) first, then handover (the
user signs in on *your* browser). Reach for this only when you specifically need to drive a
browser running somewhere else: the user's own logged-in Chrome, or a Camoufox on another host.

`browser connect <url>` attaches to it and picks the backend from the URL.

## The user's own Chrome, over the internet (CDP)

The user launches Chrome with a debug port and exposes it through any http tunnel:

```bash
# On the user's machine:
chrome --remote-debugging-port=9222
cloudflared tunnel --url http://localhost:9222      # or ngrok, tailscale, a LAN IP, etc.

# Agent side:
browser connect http://<tunnel-host>:<port>          # resolves /json/version, drives via CDP
```

The full helper surface works over CDP: `snapshot`, `click e5`, `type`, `screenshot`, navigation.
The accessibility snapshot and ref machinery run as in-page JavaScript, so they behave the same as
on Camoufox. Chrome reports its own internal host in the debug websocket URL; `connect` rewrites
it to the host you connected through, so this works across the internet.

Stealth is Camoufox's job. A connected Chrome is driven as-is, with the user's real profile and
sessions, which is exactly the point here.

## A remote Camoufox (native BiDi)

If you are pointing at a Camoufox running on another machine (not stock Chrome), give it the BiDi
websocket directly:

```bash
browser connect ws://<host>:<port>/session
```

## Notes

- Session state records the endpoint under `/tmp/vesta-browser-<session>.cdp-ws` (or `.bidi-ws`),
  so the daemon reconnects across CLI calls. `browser stop` clears it; it never kills a browser
  you connected to but did not launch.
- `browser doctor` shows the active session and backend.
