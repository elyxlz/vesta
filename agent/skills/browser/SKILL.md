---
name: browser
description: Browse, navigate, click, fill forms, screenshot, or scrape web pages via CDP.
---

# Browser

Raw Chrome DevTools Protocol. Accessibility-tree snapshots with numbered refs (`e1`, `e2`)
for the ergonomic path, and `click(x, y)` + screenshots for everything accessibility can't see.
The helpers are Python, short, and agent-editable. When something is missing, write it.

`SharedArrayBuffer` is enabled by default, so web apps that require cross-origin isolation
(COEP `require-corp` / COOP `same-origin`) load and render normally. No stealth or Xvfb
workarounds are needed for those apps.

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
browser screenshot [--path PATH] [--full-page] [--webp] [--region X,Y,W,H] [--quality N]
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

## Screenshots

Screenshots are costly in context: prefer `--webp` (5-10x smaller than PNG) and `--region` to
clip to the part that matters. Use PNG only when you need lossless output (e.g. pixel-diffing UI
state). See the `browser screenshot` flags in the command reference.

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

If you figured out something non-obvious about a site or mechanic, or wrote a broadly useful
helper, contribute it upstream before you finish via the `upstream-pr` skill. Three kinds of
upstreamable work, in order of frequency:

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

Flow: edit locally (takes effect immediately via `uv tool install --editable`), verify, then use
the `upstream-pr` skill to open a PR to `elyxlz/vesta`.

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

`browser launch --stealth` (see command reference) is on by default; disable it entirely with
`VESTA_BROWSER_NO_STEALTH=1`. Cloudflare Turnstile: see `interaction-skills/` and
`stealth.py::solve_cf_turnstile()`.

## Handover (let the user sign in on your browser)

Some sites (Microsoft/Google sign-in, banking) fingerprint automated browsers even under
stealth, and locked tenants block device-code and scripted auth outright. The way through is to
let the **user** drive your real headed Chrome: they sign in once by hand, then you reuse the
session cookies. `browser handover` wraps the plumbing (headed Chrome under Xvfb, `x11vnc`,
`websockify`) but serves a clean Vesta-branded page that auto-connects, so what the user opens
looks like Vesta, not a sketchy remote-desktop applet.

The user is usually on a different machine, so the page needs a public URL. Register a
`--public` vestad service (see the `service` skill) for a port, hand that port to
`handover start`, and give the user the tunnel route:

```bash
# 1. public port + route (idempotent: same port each call)
PORT=$(~/agent/skills/service/scripts/register-service browser-handover --public)

# 2. bring up the headed browser + branded page, pointed at the sign-in URL
browser handover start --port "$PORT" --url "https://outlook.office.com/mail/"

# 3. send the user this link (vestad proxies the websocket through it):
#    $VESTAD_TUNNEL/agents/$AGENT_NAME/browser-handover/handover.html
```

The page is generic: it says only "Vesta's browser". Tell the user what to do in chat, framed
plainly, e.g. "I need you to sign in on my browser. Connect with this link and log in there:
<link>." When they are signed in you keep the session, not their password.

While they sign in, watch for completion however the site exposes it. To talk to the handover
browser (poll for a cookie or token, screenshot), set `BROWSER_SESSION=handover` first, e.g.
`BROWSER_SESSION=handover browser evaluate "location.href"`. When finished, capture what you need
and tear it all down:

```bash
browser handover status                 # {chrome, openbox, x11vnc, websockify, web_port}
browser handover stop                   # stops VNC + WM + Chrome, removes the web root
```

The handover profile persists at `~/.browser/handover`, so afterwards you can reuse the cookies
headless with `browser launch --stealth --user-data-dir ~/.browser/handover`.

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
  hand the sign-in to the user with `browser handover`.
- **Stale refs**: take a fresh `browser snapshot` after navigation or major DOM change.
- **Xvfb not running**: `screen -dmS xvfb Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp`.
