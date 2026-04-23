# Browser Setup

The Vesta Docker image installs the browser CLI and Chromium at build time. These are the steps
the Dockerfile runs; follow them manually only if you're setting up outside the container.

## Install

```bash
# 1. Chromium binary (via playwright-core's installer)
npx -y playwright-core install --with-deps chromium

# 2. The browser CLI, installed editable so agent edits to helpers.py take effect immediately
uv tool install --editable ~/agent/skills/browser/cli

# Verify
command -v browser
browser --help
```

`uv tool install --editable` links the CLI script to the source checkout. When the agent edits
`~/agent/skills/browser/cli/src/vesta_browser/helpers.py` the next `browser` call picks up the
change without reinstalling.

## Xvfb for stealth mode

Headless Chrome still leaks automation signals even with the full stealth arg set. For sites
with aggressive bot detection, run headed on a virtual display:

```bash
apt-get install -y xvfb                                  # one-time
screen -dmS xvfb Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp
DISPLAY=:99 browser launch --stealth
```

Add the Xvfb start line to `~/agent/prompts/restart.md` so it comes back up on container restart.

## Remote assist (user takeover)

Install these when a site defeats stealth and you need the user to log in via noVNC:

```bash
apt-get install -y novnc x11vnc openbox xdotool scrot
```

See SKILL.md § "VNC takeover" for the flow.

## Connecting to the user's real browser

When Vesta runs on the same LAN as the user and you need *their* session cookies, have them
start Chrome with remote debugging and `browser connect`:

```bash
# User side (on their machine):
google-chrome --remote-debugging-port=9222

# Vesta side:
browser connect http://<user-ip>:9222
```

## Environment variables

- `BROWSER_SESSION`: namespaces socket, pid, port, and refs. Default: `default`.
- `VESTA_BROWSER_CDP_WS`: override the CDP websocket URL (for remote or connected browsers).
- `VESTA_BROWSER_CDP_PORT`: override the local CDP port (auto-set by `browser launch`).
- `VESTA_BROWSER_NO_STEALTH=1`: skip webdriver hide and UA scrub on attach.
- `VESTA_BROWSER_NO_SANDBOX=1`: add `--no-sandbox` (useful in container, root-as-user).
- `VESTA_BROWSER_EXECUTABLE`: path to a specific Chromium binary.
