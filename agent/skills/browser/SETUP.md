# Browser Setup

The Vesta Docker image installs the browser CLI at build time. Camoufox itself is **not** baked
in: it is fetched (and cached) on the first `browser launch`, so the image stays small and the
browser updates without a rebuild.

## Install

```bash
# CLI, installed editable so agent edits to helpers.py take effect immediately
uv tool install --editable ~/agent/skills/browser/cli

# Verify
command -v browser
browser --help
browser doctor        # Camoufox install state + arch asset
```

`uv tool install --editable` links the CLI script to the source checkout. Editing
`~/agent/skills/browser/cli/src/vesta_browser/helpers.py` takes effect on the next `browser` call
without reinstalling.

## First launch fetches Camoufox

The first `browser launch` downloads the pinned Camoufox release for the host arch (arm64 or
x86_64, ~650 MB) from GitHub, verifies its sha256, and extracts it to
`~/.cache/camoufox/<version>/`. That first launch takes a while; every launch after is instant.
No Chromium, no Xvfb, no display: Camoufox runs headless and fully fingerprint-spoofed. Check
state with `browser doctor`.

It does need GTK3, which the image installs (headless still runs GTK init). Without it Camoufox
exits 255 before BiDi with `libgtk-3.so.0: cannot open shared object file`. On a non-vesta image
install GTK3: `libgtk-3-0t64` on Debian trixie and later, `libgtk-3-0` on bookworm and earlier.

## Handover dependencies

`browser handover` (letting the user sign in on the agent's headed browser when account trust, not
fingerprint, is the wall) needs four packages, which the image installs. `xvfb` is the headless X
server the headed browser renders on; `novnc` provides `websockify` plus the noVNC client assets
under `/usr/share/novnc`, which the branded page symlinks. On a non-vesta image:

```bash
apt-get install -y xvfb novnc x11vnc openbox
```

`browser doctor` reports whether these are present. See SKILL.md § "Handover" for the flow.

## Connecting to a remote browser

`browser connect` attaches to a browser running elsewhere (a LAN box, or the user's own machine
over a tunnel). It picks the backend from the URL:

```bash
# The user's own Chrome (CDP). They launch Chrome with a debug port and expose it:
#   chrome --remote-debugging-port=9222
#   cloudflared tunnel --url http://localhost:9222   (or any http tunnel)
browser connect http://<tunnel-host>:<port>          # resolves /json/version, drives via CDP

# A remote Camoufox (native BiDi):
browser connect ws://<host>:<port>/session
```

Over a tunnel, Chrome reports its own internal host in the websocket URL; `connect` rewrites it
to the host you connected through, so the full helper surface (snapshot, click, type, screenshot)
works across the internet. Stealth is Camoufox's job; a connected Chrome is driven as-is.

## Environment variables

- `BROWSER_SESSION`: namespaces socket, pid, bidi-ws, and log. Default: `default`.
- `VESTA_BROWSER_BIDI_WS`: override the BiDi websocket URL (for remote or connected browsers).
- `VESTA_BROWSER_EXECUTABLE`: path to a specific Camoufox binary (skips the fetch/cache step).
