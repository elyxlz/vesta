---
name: browser
description: Use for "browse", "open a website", "navigate to", "click", "fill form", "take screenshot", "scrape", or any web page interaction. Ref-based accessibility targeting plus coordinate clicks and raw CDP.
---

# Browser

Raw Chrome DevTools Protocol. Accessibility-tree snapshots with numbered refs (`e1`, `e2`)
for the ergonomic path, and `click(x, y)` + screenshots for everything accessibility can't see.
The helpers are Python, short, and agent-editable. When something is missing, write it.

**Setup**: [SETUP.md](SETUP.md)

## Search first

Before inventing an approach to a site, check `domain-skills/<host>/` for saved recipes and
`interaction-skills/` for reusable mechanics (dialogs, iframes, shadow DOM, uploads, scrolling,
dropdowns). When you open or navigate to a URL, the CLI prepends a banner listing any matching
recipes. Read them.

```bash
# List everything we know about a site
ls ~/agent/skills/browser/domain-skills/amazon/
# Or search broadly
rg "<selector or keyword>" ~/agent/skills/browser/domain-skills/ ~/agent/skills/browser/interaction-skills/
```

## Two ways to drive the browser

### 1. Bash subcommands (ref-based, agent-ergonomic)

```bash
browser launch --stealth                # once per session
browser open "https://example.com"      # opens a new tab and prints a snapshot with e1, e2 refs
browser click e5                        # click the ref
browser type e3 "hello" --submit        # type and press Enter
browser snapshot --interactive          # only interactive elements
browser screenshot --path /tmp/s.png    # PNG of current viewport
```

Every action command returns an updated snapshot. Use refs from the **most recent** snapshot only;
a fresh snapshot invalidates older refs.

### 2. Python stdin mode (programmatic, multi-step flows)

```bash
browser <<'PY'
goto("https://news.ycombinator.com")
wait_for_load()
print(page_info())
stories = js("[...document.querySelectorAll('.athing .titleline a')].map(a => ({title: a.innerText, url: a.href}))")
print(stories[:5])
PY
```

All `helpers.py` primitives are pre-imported: `goto`, `new_tab`, `switch_tab`, `list_tabs`,
`ensure_real_tab`, `click` (coordinate), `type_text`, `press_key`, `scroll`, `screenshot`,
`page_info`, `js`, `cdp` (raw escape hatch), `drain_events`, `pending_dialog`, `http_get`,
`wait`, `wait_for_load`, `wait_for_text`, `wait_for_url`, `upload_file`, `iframe_target`.
Plus ref-based variants: `click_ref`, `type_ref`, `hover_ref`.

## Command reference

```bash
# Session
browser launch --stealth                          # Scrapling anti-detection args + UA scrub
browser launch --headless                         # headless (faster; more fingerprintable)
browser launch --user-data-dir ~/.config/chrome   # reuse an existing profile
browser connect http://192.168.1.10:9222          # attach to a remote Chrome
browser stop                                      # stop this session
browser stop-all                                  # stop everything
browser sessions                                  # list active sessions

# Navigation
browser open "URL"                                # new tab + navigate + snapshot
browser navigate "URL"                            # current tab
browser reload / back / forward

# Reads
browser snapshot [--interactive]                  # accessibility tree with e1/e2 refs
browser screenshot [--path PATH] [--full-page]
browser pdf [--path PATH]
browser evaluate "() => document.title"           # run JS in the page
browser cdp "Page.getFrameTree"                   # raw CDP escape hatch
browser cdp "Network.setCookie" '{"name":"k","value":"v","domain":".example.com"}'
browser http-get "https://api.example.com/v1/x"   # no browser, pure HTTP

# Actions on refs
browser click e5 [--double|--right]
browser click --at 320 180                        # coordinate click (goes through shadow DOM)
browser type e3 "text" [--submit] [--slowly]
browser press Enter
browser press a --modifiers Control               # Ctrl+A
browser hover e2
browser scroll --down 500 / --up 300 / e7

# Tabs
browser tabs
browser focus <target_id>
browser close <target_id>

# Waits
browser wait --text "Welcome"
browser wait --url "**/dashboard"
browser wait --time 2000
browser wait --load-state load
```

## Refs vs coordinates

Use **refs** (e1, e2) first. They're semantic, survive layout changes within a snapshot, and
work on 95% of pages.

Drop to **`click(x, y)` / `browser click --at X Y`** when:
- The target is inside a shadow DOM or cross-origin iframe (compositor-level click passes through)
- The accessibility tree is misleading or the element has no ARIA role
- You're following a screenshot-based flow (read pixel, click pixel, re-screenshot to verify)

`Input.dispatchMouseEvent` hit-tests in Chrome's browser process; the click lands at that point
regardless of DOM structure.

## When you need something new

Helpers are in `cli/src/vesta_browser/helpers.py`. The package is installed editable, so when
you edit that file the next `browser` call uses the new code without rebuilding. Add a helper
when you find yourself repeating the same CDP dance. Keep it short.

```bash
$EDITOR ~/agent/skills/browser/cli/src/vesta_browser/helpers.py
# add your helper, save
browser <<'PY'
my_new_helper(...)   # already available
PY
```

## Contribute back what you learn

**If you figured out something non-obvious about a site or mechanic, or wrote a helper that's
broadly useful, contribute it upstream before you finish.** The agent loop on a site gets
better only because past agents wrote down what they learned. Use the existing `upstream-pr`
skill.

Three kinds of upstreamable work, in order of frequency:

1. **Domain skill** under `domain-skills/<host>/<topic>.md`. Private APIs, stable selectors,
   framework quirks, URL patterns, waits, traps. See the pattern in existing skill files.
2. **Interaction skill** under `interaction-skills/<mechanic>.md`. Reusable mechanics (new
   dialog pattern, a shadow-DOM trick, an upload variant).
3. **New helper in `helpers.py`** when the primitive is broadly useful (a new CDP wrapper,
   a smarter `wait_for_X`, a hardened `http_get` header handler). Filter: would every other
   Vesta benefit, or is this a personal quirk? Upstream if generic. Keep it local if
   site-specific or user-specific (put it in a `domain-skills/` recipe instead).

What *not* to put anywhere shared:
- Pixel coordinates (break on viewport/zoom). Describe how to locate the target.
- Narration of the specific task you just did.
- Secrets, cookies, session tokens, personal credentials.

Flow: edit the file locally (it takes effect immediately thanks to `uv tool install --editable`),
verify it works, then use the `upstream-pr` skill to open a PR to `elyxlz/vesta`.

## Multi-session (parallel sub-agents)

Each sub-agent should set a unique `BROWSER_SESSION` so they don't share a daemon / socket /
ref cache. Port auto-allocation starts at 9222.

```bash
BROWSER_SESSION=agent-1 browser launch --headless
BROWSER_SESSION=agent-1 browser open "https://a.com"

BROWSER_SESSION=agent-2 browser launch --headless
BROWSER_SESSION=agent-2 browser open "https://b.com"
```

Each session state lives under `/tmp/vesta-browser-<name>.*` (socket, pid, cdp-port, log,
refs cache). `browser stop` cleans its own; `browser stop-all` nukes everything.

Memory warning: each Chrome uses 200 to 400 MB. Running 3+ concurrently on a memory-constrained
host can OOM. Prefer sequential for wide-scrape tasks.

## Stealth

`browser launch --stealth` enables:
- 58 anti-detection Chrome args (Scrapling)
- `--disable-blink-features=AutomationControlled` (always on)
- `navigator.webdriver` returns `undefined`, `navigator.plugins` populated, `navigator.languages` set
- UA `Headless` stripped via `Emulation.setUserAgentOverride`

For maximum stealth, run headed via Xvfb:

```bash
screen -dmS xvfb Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp
DISPLAY=:99 browser launch --stealth
```

Disable stealth entirely with `VESTA_BROWSER_NO_STEALTH=1`.

Cloudflare Turnstile: see `interaction-skills/` and `stealth.py::solve_cf_turnstile()`.

## VNC takeover (when stealth loses)

Some sites (Google sign-in, banking) fingerprint automated browsers even under stealth. Hand
control to the user via noVNC: they log in once, you reuse the persistent profile.

```bash
apt-get install -y novnc x11vnc openbox xdotool       # one-time
screen -dmS xvfb Xvfb :99 -screen 0 1280x720x24
screen -dmS openbox bash -c 'DISPLAY=:99 openbox'
DISPLAY=:99 chromium --no-sandbox --disable-gpu \
  --user-data-dir=$HOME/.browser/profile \
  --window-size=1280,720 'https://example.com' &
screen -dmS x11vnc x11vnc -display :99 -nopw -forever -shared -rfbport 5900
screen -dmS websockify websockify --web=/usr/share/novnc <PORT> localhost:5900
# send the user http://<LAN_IP>:<PORT>/vnc.html
# when they're done:
screen -X -S x11vnc quit; screen -X -S websockify quit
# then use `browser launch --stealth --user-data-dir ~/.browser/profile` to reuse their cookies
```

## Raw CDP escape hatch

Anything not wrapped:

```bash
browser cdp "Network.clearBrowserCookies"
browser cdp "Page.setDownloadBehavior" '{"behavior":"allow","downloadPath":"/tmp"}'
browser cdp "Runtime.evaluate" '{"expression":"alert(1)"}'
```

Or from stdin mode: `cdp("Network.getCookies", urls=["https://example.com"])`.

## Troubleshooting

- **`no Chrome for this session`**: run `browser launch` first, or set `VESTA_BROWSER_CDP_WS`.
- **`daemon did not come up`**: check `/tmp/vesta-browser-<session>.log` for the reason.
- **Bot detection / blocked**: `browser screenshot` to see the page, then try `--stealth`, or
  drop to VNC takeover.
- **Stale refs**: take a fresh `browser snapshot` after navigation or major DOM change.
- **Xvfb not running**: `screen -dmS xvfb Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp`.
