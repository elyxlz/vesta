---
name: browser
description: Browse, navigate, click, fill forms, screenshot, or scrape web pages with a stealth (Camoufox) browser.
---

# Browser

Camoufox (anti-detection Firefox that spoofs its fingerprint in C++ below JS) driven over raw
WebDriver BiDi. Accessibility-tree snapshots with numbered refs (`e1`, `e2`) for the ergonomic
path; `click(x, y)` + screenshots for what accessibility can't see. Helpers are Python, short,
agent-editable. When something is missing, write it.

Stealth is structural, not a flag: Camoufox is always fingerprint-spoofed, and headless leaks
nothing. Each profile gets one coherent fingerprint, stable across restarts, different across
profiles.

**Setup**: [SETUP.md](SETUP.md)

## Search first

Before inventing an approach to a site, check `domain-skills/<host>/` for saved recipes and
`interaction-skills/` for reusable mechanics (dialogs, iframes, shadow DOM, uploads, scrolling,
dropdowns). Navigating to a URL prepends a banner listing matching recipes. Read them.

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
browser open "https://example.com"      # new tab + snapshot with e1, e2 refs
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
browser launch --mode screenshot                  # report screenshots, not the a11y tree
browser launch --user-data-dir ~/.browser/work    # reuse / isolate a profile (own fingerprint)
browser connect http://192.168.1.10:9222          # attach to user's Chrome (CDP), even over a tunnel
browser connect ws://192.168.1.10:9222/session    # attach to a remote Camoufox BiDi endpoint
browser mode screenshot                           # switch perception: a11y | screenshot | both
browser stop                                      # stop this session
browser stop-all                                  # stop everything
browser sessions                                  # list active sessions
browser doctor                                    # Camoufox install + session health

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
browser fetch "URL" --navigate-first              # render through stealth browser, return text

# Actions on refs
browser click e5 [--double|--right]
browser click --at 320 180                        # coordinate click (through shadow DOM)
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
clip to what matters. Use PNG only for lossless output (e.g. pixel-diffing UI state). Camoufox
captures PNG and JPEG natively; `--webp` is encoded as JPEG.

## Perception: a11y tree or screenshots

Pick how the browser reports back after each action, once per session:

```bash
browser mode a11y             # default: every action returns the a11y tree with e1/e2 refs
browser mode screenshot       # every action returns a screenshot path instead
browser mode both             # return both
browser mode                  # print the current mode
browser launch --mode screenshot   # pick the mode at launch instead
```

In **a11y** mode, drive with refs (`browser click e5`). In **screenshot** mode, read
`/tmp/vesta-browser-view.png`, find the target's pixel, and use coordinate actions
(`browser click --at X Y`). `browser snapshot` and `browser screenshot` always work regardless
of mode when you want the other view on demand.

## Refs vs coordinates

Use **refs** (e1, e2) first. They're semantic, survive layout changes within a snapshot, and
work on 95% of pages. Refs come from the a11y snapshot, which computes each element's role and
accessible name with the full W3C accname algorithm.

Drop to **`click(x, y)` / `browser click --at X Y`** when:
- The target is inside a shadow DOM or cross-origin iframe (input-level click passes through)
- The a11y tree is misleading or the element has no ARIA role
- You're following a screenshot-based flow (read pixel, click pixel, re-screenshot to verify)

`input.performActions` dispatches a real pointer event at that viewport point regardless of DOM
structure.

## When stealth isn't enough (escalation)

Camoufox stealth handles most sites. When one still blocks you, escalate in this order,
most-preferred first:

1. **Stealth (default).** Just `browser launch`. Fingerprint spoofed in C++, so most
   automated-browser detection never fires. Try this first, always.
2. **Handover (primary fallback).** If a site gates on *account trust* (sign-in walls, banking,
   locked tenants) rather than fingerprint, hand your headed browser to the user to sign in once;
   the session persists in the shared profile and you resume automating.
   `browser handover start --url "<sign-in URL>"` registers the public route and returns a
   ready-to-send `user_url` (send the user that link, not `web_port`). See
   [interaction-skills/handover.md](interaction-skills/handover.md).
3. **Remote-control the user's own browser (last resort).** Only when you specifically need *their*
   logged-in Chrome, drive it over a tunnel with `browser connect`. See
   [interaction-skills/remote-control.md](interaction-skills/remote-control.md).

## More

- [interaction-skills/advanced-usage.md](interaction-skills/advanced-usage.md) : extending helpers, multi-session, the raw BiDi escape hatch, how stealth works, contributing back
- [interaction-skills/](interaction-skills/) : reusable mechanics (dialogs, iframes, shadow DOM, uploads, tabs)

## Troubleshooting

- **`no Camoufox for this session`**: run `browser launch` first, or set `VESTA_BROWSER_BIDI_WS`
  to a remote BiDi endpoint.
- **`daemon did not come up`**: check `/tmp/vesta-browser-<session>.log` and `browser doctor`.
- **First launch is slow**: Camoufox (~650 MB) is fetched and cached under
  `~/.cache/camoufox/<version>/` on first `browser launch`; later launches are instant.
- **Bot detection / blocked**: `browser screenshot` to see the page. Camoufox is already stealthy,
  so a block is usually account-trust, geo/IP, or a CAPTCHA: try handover.
- **Stale refs**: take a fresh `browser snapshot` after navigation or major DOM change.
