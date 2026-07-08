---
name: browser
description: Browse, navigate, click, fill forms, screenshot, or scrape web pages with a stealth (Camoufox) browser.
---

# Browser

Camoufox (an anti-detection Firefox that spoofs its fingerprint in C++ below JS) driven over raw
WebDriver BiDi. Accessibility-tree snapshots with numbered refs (`e1`, `e2`) for the ergonomic
path, and `click(x, y)` + screenshots for everything accessibility can't see. The helpers are
Python, short, and agent-editable. When something is missing, write it.

Stealth is structural, not a flag: Camoufox is always fingerprint-spoofed, and headless leaks
nothing (unlike stock Chromium). Each profile gets one coherent fingerprint, stable across
restarts, different across profiles.

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
browser launch                          # once per session (fetches Camoufox on first use)
browser open "https://example.com"      # opens a new tab and prints a snapshot with e1, e2 refs
browser click e5                        # click the ref
browser type e3 "hello" --submit        # type and press Enter
browser snapshot --interactive          # only interactive elements
browser screenshot --path /tmp/s.png    # PNG of current viewport
```

Every action command returns an updated snapshot. Use refs from the **most recent** snapshot only;
a fresh snapshot invalidates older refs, and navigating away invalidates them all.

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
`page_info`, `set_viewport`, `js`, `bidi` (raw escape hatch), `drain_events`, `pending_dialog`,
`http_get`, `fetch_navigate`, `wait`, `wait_for_load`, `wait_for_text`, `wait_for_url`,
`upload_file`, `iframe_target`. Plus ref-based variants: `click_ref`, `type_ref`, `hover_ref`,
`scroll_to_ref`.

## Command reference

```bash
# Session
browser launch                                    # fetch (first time) + launch Camoufox, headless
browser launch --vision                           # ... and report back with screenshots, not the a11y tree
browser launch --user-data-dir ~/.browser/work    # reuse / isolate a profile (own fingerprint)
browser connect http://192.168.1.10:9222          # attach to the user's own Chrome (CDP), even over a tunnel
browser connect ws://192.168.1.10:9222/session    # attach to a remote Camoufox BiDi endpoint
browser mode screenshot                           # switch perception: a11y | screenshot | both
browser stop                                      # stop this session
browser stop-all                                  # stop everything
browser sessions                                  # list active sessions
browser doctor                                    # report Camoufox install + session health

# Navigation
browser open "URL"                                # new tab + navigate + snapshot
browser navigate "URL"                            # current tab
browser reload / back / forward

# Reads
browser snapshot [--interactive]                  # accessibility tree with e1/e2 refs
browser screenshot [--path PATH] [--full-page] [--webp] [--region X,Y,W,H] [--quality N]
browser pdf [--path PATH]
browser evaluate "document.title"                 # run JS in the page
browser bidi "browsingContext.getTree"            # raw WebDriver BiDi escape hatch
browser bidi "storage.getCookies" '{"filter":{"domain":"example.com"}}'
browser http-get "https://api.example.com/v1/x"   # no browser, pure HTTP
browser fetch "URL" --navigate-first              # render through the stealth browser, return text

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
browser focus <context_id>
browser close <context_id>

# Waits
browser wait --text "Welcome"
browser wait --url "**/dashboard"
browser wait --time 2000
browser wait --load-state load
```

## Screenshots

Screenshots are costly in context: prefer `--webp` (much smaller than PNG) and `--region` to
clip to the part that matters. Use PNG only when you need lossless output (e.g. pixel-diffing UI
state). Camoufox captures PNG and JPEG natively; `--webp` is encoded as JPEG.

## Perception: a11y tree or screenshots

You pick how the browser reports back after each action, once per session:

```bash
browser mode a11y         # default: every action returns the accessibility tree with e1/e2 refs
browser mode screenshot   # every action returns a screenshot path instead (work from the image)
browser mode both         # return both
browser mode              # print the current mode
browser launch --vision   # shortcut for screenshot mode at launch
```

In **a11y** mode, drive with refs (`browser click e5`). In **screenshot** mode, read
`/tmp/vesta-browser-view.png`, find the target's pixel, and use coordinate actions
(`browser click --at X Y`). `browser snapshot` and `browser screenshot` always work regardless
of mode when you want the other view on demand.

## Refs vs coordinates

Use **refs** (e1, e2) first. They're semantic, survive layout changes within a snapshot, and
work on 95% of pages. Refs come from the accessibility snapshot, which computes each element's
role and accessible name with the full W3C accname algorithm.

Drop to **`click(x, y)` / `browser click --at X Y`** when:
- The target is inside a shadow DOM or cross-origin iframe (input-level click passes through)
- The accessibility tree is misleading or the element has no ARIA role
- You're following a screenshot-based flow (read pixel, click pixel, re-screenshot to verify)

`input.performActions` dispatches a real pointer event at that viewport point regardless of DOM
structure.

## When you need something new

Helpers are in `cli/src/vesta_browser/helpers.py`. The package is installed editable, so when
you edit that file the next `browser` call uses the new code without rebuilding. Add a helper
when you find yourself repeating the same BiDi dance. Keep it short.

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
3. **New helper in `helpers.py`** when the primitive is broadly useful (a new BiDi wrapper,
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
browser. Each session also gets its own profile (and therefore its own fingerprint).

```bash
BROWSER_SESSION=agent-1 browser launch
BROWSER_SESSION=agent-1 browser open "https://a.com"

BROWSER_SESSION=agent-2 browser launch
BROWSER_SESSION=agent-2 browser open "https://b.com"
```

Each session's state lives under `/tmp/vesta-browser-<name>.*` (socket, pid, bidi-ws, log).
`browser stop` cleans its own; `browser stop-all` nukes everything.

Memory warning: each Camoufox uses several hundred MB. Running 3+ concurrently on a
memory-constrained host can OOM. Prefer sequential for wide-scrape tasks.

## Stealth

Stealth is built in. Camoufox spoofs the fingerprint (navigator, screen, WebGL, timezone,
fonts, `navigator.webdriver=false`) in patched Gecko C++, below anything JS can observe, so it
survives the CreepJS-tier `Function.prototype.toString` / descriptor / stack-frame battery that
stock Chromium + CDP injection cannot. Each profile draws one coherent fingerprint preset
(`presets.py`), stable across restarts and distinct across profiles. There is no `--stealth`
flag to toggle and no Xvfb to provision; headless is the stealthy default.

## Handover (when trust, not fingerprint, is the wall)

Some sites (Google sign-in, banking) gate on account trust and want a human once. Hand the live
headed browser to the user over a clean, Vesta-branded page and let them sign in by hand:

```bash
browser handover start --url "https://accounts.google.com" --port <service-port>
browser handover status
browser handover stop
```

`handover start` launches headed Camoufox on the shared profile under an X server, bridges it out
(`x11vnc` + `websockify` serving the branded noVNC page), and returns the page to send the user.
Whatever they sign into persists in the shared profile, so the agent's everyday browser grows more
trusted over time. Get the public URL from a `--public` vestad service route (vestad proxies the
websocket), and tell the user the task in chat (the page itself stays generic). Needs the handover
binaries (see SETUP.md).

## Raw BiDi escape hatch

Anything not wrapped:

```bash
browser bidi "browsingContext.getTree"
browser bidi "storage.setCookie" '{"cookie":{"name":"k","value":"v","domain":"example.com"}}'
browser bidi "script.evaluate" '{"expression":"1+1","awaitPromise":true}'
```

Or from stdin mode: `bidi("storage.getCookies", filter={"domain": "example.com"})`. The daemon
injects the current `context` (or `target`) where the command shape needs one.

## Troubleshooting

- **`no Camoufox for this session`**: run `browser launch` first, or set `VESTA_BROWSER_BIDI_WS`
  to a remote BiDi endpoint.
- **`daemon did not come up`**: check `/tmp/vesta-browser-<session>.log` for the reason, and
  `browser doctor` for install/session state.
- **First launch is slow**: Camoufox (~650 MB) is fetched and cached under
  `~/.cache/camoufox/<version>/` on first `browser launch`; subsequent launches are instant.
- **Bot detection / blocked**: `browser screenshot` to see the page. Camoufox is already
  stealthy, so a block is usually account-trust, geo/IP, or a CAPTCHA, so try handover.
- **Stale refs**: take a fresh `browser snapshot` after navigation or major DOM change.
