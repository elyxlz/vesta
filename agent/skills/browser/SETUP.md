# Browser Setup

## Install Dependencies

```bash
# 1. Node.js (if not installed)
curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs

# 2. Xvfb for stealth mode (virtual display)
apt-get install -y xvfb

# 3. Build and install the browser CLI
cd ~/vesta/skills/browser/cli && npm install && npm run build && npm install -g .

# 4. Install Chromium (matched to playwright-core version)
npx playwright-core install --with-deps chromium
```

## Stealth Mode (Bypass Bot Detection)

Many sites (Cloudflare, etc.) detect and block automated browsers. The browser CLI has
built-in stealth but **headless mode still gets caught**. For maximum stealth:

### Xvfb (Virtual Display)

Xvfb lets you run a headed browser without a physical screen — sites see a normal browser
window, not headless automation.

```bash
# Install Xvfb (first time only)
apt-get install -y xvfb

# Start virtual display (once per session, before launching browser)
screen -dmS xvfb Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp
```

### What Stealth Does Under the Hood

The browser CLI applies multiple layers automatically:

1. **`navigator.webdriver` hidden** — injected via `addInitScript` on every page, so
   `navigator.webdriver` returns `undefined` instead of `true`
2. **`--disable-blink-features=AutomationControlled`** — Chrome flag that removes the
   `AutomationControlled` feature, preventing sites from detecting Chromium automation
3. **Headed via Xvfb** — runs a real browser window on a virtual display, avoiding all
   the fingerprinting differences between headless and headed Chrome (screen dimensions,
   WebGL renderer, missing plugins, etc.)

## Troubleshooting — Remote Control

If something doesn't work with the local browser (login walls, CAPTCHAs, 2FA, missing
cookies, profile lock errors, or anything requiring the user's authenticated session), **ask
the user to let you connect to their browser remotely** instead of retrying locally:

1. Ask the user to open their browser with remote debugging:
   - **Brave**: `brave --remote-debugging-port=9222`
   - **Chrome**: `google-chrome --remote-debugging-port=9222`
   - **Edge**: `microsoft-edge --remote-debugging-port=9222`
   - Or add `--remote-debugging-port=9222` to their browser shortcut for always-on access
2. Ask the user for their machine's IP address (or `localhost` if Vesta runs on the same machine)
3. Connect: `browser connect http://<ip>:9222`
4. Now you control their actual browser — with all their cookies, logins, and extensions

This is the preferred fallback for any authentication or profile issue.
