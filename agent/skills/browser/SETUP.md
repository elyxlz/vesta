# Browser Setup

The Vesta Docker image installs the browser CLI at build time. Camoufox itself is **not** baked
into the image: it is fetched (and cached) on the first `browser launch`, so the image stays
small and the browser updates without a rebuild.

## Install

```bash
# The browser CLI, installed editable so agent edits to helpers.py take effect immediately
uv tool install --editable ~/agent/skills/browser/cli

# Verify
command -v browser
browser --help
browser doctor        # shows Camoufox install state + arch asset
```

`uv tool install --editable` links the CLI script to the source checkout. When the agent edits
`~/agent/skills/browser/cli/src/vesta_browser/helpers.py` the next `browser` call picks up the
change without reinstalling.

## First launch fetches Camoufox

The first `browser launch` downloads the pinned Camoufox release for the host arch (arm64 or
x86_64, ~650 MB) from GitHub, verifies its sha256, and extracts it to
`~/.cache/camoufox/<version>/`. That first launch takes a while; every launch after is instant.
No apt packages, no Chromium, no Xvfb, no display: Camoufox runs headless and is fully
fingerprint-spoofed in that mode. Check state any time with `browser doctor`.

## Handover dependencies

Install these only for `browser handover` (letting the user sign in on the agent's headed
browser when account trust, not fingerprint, is the wall). `novnc` provides `websockify` plus the
noVNC client assets under `/usr/share/novnc`, which the branded page symlinks:

```bash
apt-get install -y novnc x11vnc openbox xdotool scrot
```

See SKILL.md § "Handover" for the flow.

## Connecting to a remote Camoufox

To drive a Camoufox running on another machine, point the session at its BiDi WebSocket:

```bash
browser connect ws://<host>:<port>/session
```

## Environment variables

- `BROWSER_SESSION`: namespaces socket, pid, bidi-ws, and log. Default: `default`.
- `VESTA_BROWSER_BIDI_WS`: override the BiDi websocket URL (for remote or connected browsers).
- `VESTA_BROWSER_EXECUTABLE`: path to a specific Camoufox binary (skips the fetch/cache step).
