---
name: browser
description: Browse, navigate, click, fill forms, screenshot, or scrape web pages with a stealth (Camoufox) browser.
---

**Current interface**: run `browser daemon start` to start the daemon, then `browser exec
--session <name> [--stealth]` to run Python against that session, script on stdin (helpers
include `new_tab`, `goto_url`, `page_info`, `js`, `click_at_xy`, `fill_input`,
`capture_screenshot`, and more). The detailed reference below this block lags the CLI; run
`browser --help` for the authoritative command list.

# Browser

Camoufox (an anti-detection Firefox that spoofs its fingerprint in C++ below JS) driven over raw
WebDriver BiDi. Accessibility-tree snapshots with numbered refs (`e1`, `e2`) for the ergonomic
path, and `click(x, y)` + screenshots for everything accessibility can't see. The helpers are
Python, short, and agent-editable. When something is missing, write it.

Stealth is structural, not a flag: Camoufox is always fingerprint-spoofed, and headless leaks
nothing (unlike stock Chromium). Each profile gets one coherent fingerprint, stable across
restarts, different across profiles.

**Never assume you got caught by anti-bot.** Because the browser is genuinely stealth, a hang or
a blank page is almost never a block. The overwhelmingly common cause is boring: `open`/`navigate`
waits for the page `load` event, and heavy JS/SPA sites (airlines, banks, booking flows) fire it
late or never, so the command times out even though the page rendered fine. The same cause also
returns **clean** with `document.body.innerText.length` at 0, and that second symptom is the one
that fools you: the command SUCCEEDED, so "did it time out?" answers no and you walk straight past
this paragraph. Re-navigating the same context with `"wait":"none"` renders it. Rule out the boring
cause FIRST: (1) take a `snapshot` or `screenshot` anyway, the content is usually already there;
(2) navigate via BiDi with a lighter wait so you return before full load:
`browser bidi browsingContext.navigate '{"context":"<ctx>","url":"<url>","wait":"interactive"}'`
(or `"wait":"none"`). Only after the page truly never renders across these should you even
consider a block, and even then suspect a cookie/consent wall or a redirect before "anti-bot".

**One concrete instance: a `browser open` that sits there.** `open` creates a tab (BiDi
`browsingContext.create {"type":"tab"}`), and in some containers that one call never gets an
answer. It waits the full **60s** response bound, then takes over a context the browser already
has rather than failing, preferring one showing no page. So `open` still lands, just slowly, and
what you get back is an existing context rather than a fresh tab: run `browser tabs` before
assuming you have two. Let it reach the timeout instead of killing it, since the error names the
exact call that stalled, while terminating early leaves you with "it hung" and sends you hunting
a block that is not there. Once you have seen it on a box, reach for **`browser navigate <url>`**,
which skips tab creation and returns at once.

**When a button does nothing, check the click's exit code first.** `browser click <ref>` exits
non-zero and names what was topmost at the point it clicked when that is not your element, on
stderr (`e14 is covered by <div.modal-wrap>, which took the click instead.`). That means an
invisible overlay ate it, and every retry, every coordinate fallback and every theory about
validation is wasted until it is dismissed. A modal can be absent from `innerText` and still sit
over an enabled button. See [interaction-skills/clicking.md](interaction-skills/clicking.md).

**Same rule for a stuck FORM: a submit/next button that won't advance is a validation error, not a block.** On a multi-step wizard or checkout, when "Continue"/"Submit" appears to do nothing, do NOT conclude the site is fighting automation. Read the actual state first: screenshot it, grep the DOM for a required-but-empty field (`[required]` with no value), a `.text-danger`/`[class*=error]` message, an unticked terms checkbox, or a second hidden copy of the form you filled the wrong instance of. A false wall abandoned is worse than a real wall pushed through: the overwhelmingly common blocker on a stuck submit is one missing required field.

**And the harder version: a page that appears to have NO field at all is almost never a page that cannot be filled.** "There is nowhere to type it, so this needs the user's own device" is the most expensive wrong conclusion available, because it looks like diligence. Before writing that sentence, rule out five things, in this order:
1. **A cross-origin iframe.** Identity, payment and document-upload widgets are nearly always third-party iframes, so the parent document reads as empty while the screenshot plainly shows a form. Enumerating contexts and working inside one: [interaction-skills/cross-origin-iframes.md](interaction-skills/cross-origin-iframes.md).
2. **A field behind a conditional render.** The input exists only after some control is clicked (a `v-if`/`x-show` toggled by a "Get a code" or "Enter it manually" link). If the visible call-to-action opens a new tab, click it with a capture-phase `preventDefault` so the framework's handler still runs and reveals the field without navigating away.
3. **A selector that is too specific.** Framework-rendered inputs often carry no `type` attribute, so `input[type=text]` matches nothing even though `el.type === 'text'`. Query bare `input` and filter in JS, and include `[contenteditable]` and `[role=textbox]` for masked/custom widgets. A `contenteditable` rich-text editor needs [interaction-skills/prosemirror-tiptap-editors.md](interaction-skills/prosemirror-tiptap-editors.md).
4. **A shadow root.** `querySelectorAll` never pierces one, so a web-component field is invisible to it. Walk recursively: collect matches, then recurse into every `el.shadowRoot`.
5. **Hydration timing.** A code-split step component mounts late, so an immediate query legitimately returns 0 a moment before the field exists. Re-query after a short wait or a `wait_for_text` on the expected label before concluding anything.

A genuine wall states a capability the machine lacks (a camera, a physical document, a biometric, an on-device 2FA), not merely a field you could not find.

**Parallel agents must not share a browser session**: concurrent runs on one session share tabs and can navigate each other's pages or evict each other, so give each parallel run its own `BROWSER_SESSION` (isolation details in [interaction-skills/advanced-usage.md](interaction-skills/advanced-usage.md)).

**Setup**: [SETUP.md](SETUP.md)

## Search first

Before inventing an approach to a site, check `domain-skills/<host>/` for saved recipes and
`interaction-skills/` for reusable mechanics (dialogs, tabs, cross-origin iframes, screenshots,
rich-text editors). When you open or navigate to a URL, the CLI prepends a banner listing any matching
recipes. Read them. Also check for the site's own API first: many SPAs answer their own JSON or
config endpoints with everything the page shows, so a job board, booking widget, or account flow
is often one `curl` or `browser http-get` instead of a launch, a navigation, and a snapshot.

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
`page_info`, `set_viewport`, `js`, `bidi` (raw escape hatch, keyword params:
`bidi("storage.getCookies", filter={...})`; the shell command takes one JSON blob instead),
`drain_events`, `pending_dialog`, `http_get`, `fetch_navigate`, `wait`, `wait_for_load`,
`wait_for_text`, `wait_for_url`, `upload_file`, `iframe_target`. Plus ref-based variants:
`click_ref`, `type_ref`, `hover_ref`, `scroll_to_ref`.

## Command reference

```bash
# Session
browser launch                                    # fetch (first time) + launch Camoufox, headless
browser launch --mode screenshot                  # ... and report back with screenshots, not the a11y tree
browser launch --ephemeral-profile                # isolated throwaway profile, deleted on stop
browser launch --user-data-dir ~/.browser/work    # isolated DURABLE profile, kept forever
browser connect http://192.168.1.10:9222          # attach to the user's own Chrome (CDP), even over a tunnel
browser connect ws://192.168.1.10:9222/session    # attach to a remote Camoufox BiDi endpoint
browser mode screenshot                           # switch perception: a11y | screenshot | both
browser stop [session]                            # stop this session, or the named one
browser stop-all                                  # stop every session; refuses while other sessions are live (--force overrides)
browser sessions                                  # list active sessions
browser prune                                     # report ephemeral profiles left by crashes (--yes deletes)
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

Screenshots are costly in context: prefer `--webp` and `--region` to keep them small. Format and
clipping tradeoffs: [interaction-skills/screenshots.md](interaction-skills/screenshots.md).

## Perception: a11y tree or screenshots

You pick how the browser reports back after each action, once per session:

```bash
browser mode a11y             # default: every action returns the accessibility tree with e1/e2 refs
browser mode screenshot       # every action returns a screenshot path instead (work from the image)
browser mode both             # return both
browser mode                  # print the current mode
browser launch --mode screenshot   # pick the mode at launch instead of switching after
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

**Both ref clicks and `--at` clicks are TRUSTED input; an `element.click()` from `browser js` is
not**, and the difference is invisible until it matters. An untrusted click carries no user
activation, so Firefox silently refuses anything gated on a gesture: `window.open` and
`target="_blank"` popups, clipboard writes, fullscreen, file pickers. Nothing errors, the tab just
stays `about:blank` or never appears. If the action NAVIGATES, OPENS, UPLOADS or writes outside the
page, use a real click. For ordinary in-page handlers a JS click is fine. Full story in
[interaction-skills/clicking.md](interaction-skills/clicking.md).

## When stealth isn't enough (escalation)

Camoufox stealth handles the large majority of sites. When one still blocks you, escalate in this
order, most-preferred first:

1. **Stealth (default).** Just `browser launch`. Try this first, always.
2. **Handover (primary fallback).** If a site gates on *account trust* (sign-in walls, banking,
   locked tenants) rather than fingerprint, hand your headed browser to the user to sign in once;
   the session persists in the shared profile and you resume automating. One command does it:
   `browser handover start --url "<sign-in URL>"` registers the public route itself and returns a
   ready-to-send `user_url` (send the user that link, not `web_port`). `handover stop` tears down the
   processes AND the public registration, so the route never outlives the session; confirm both. See
   [interaction-skills/handover.md](interaction-skills/handover.md).
3. **Remote-control the user's own browser (last resort).** Only when you specifically need *their*
   logged-in Chrome, drive it over a tunnel with `browser connect`. See
   [interaction-skills/remote-control.md](interaction-skills/remote-control.md).

## Picking a profile

- **Nothing** (default): the shared profile. Handover sign-ins persist here.
- **`--ephemeral-profile`**: isolated, own fingerprint, **deleted on stop**. Use for one-off runs.
- **`--user-data-dir <path>`**: isolated and **durable**, kept forever. Only for a profile you mean
  to reuse, like an account you signed into once.

`browser prune` exists for ephemeral profiles whose session was killed before it could clean up; it
walks the filesystem rather than the session registry, since the registry dies with the session.
It only ever touches the ephemeral root, never a `--user-data-dir` profile: an idle signed-in
profile and an orphan look identical to any liveness check, so intent is recorded at creation.

## More

Occasional topics live in their own files so this one stays lean:

- [interaction-skills/advanced-usage.md](interaction-skills/advanced-usage.md) : extending helpers, multi-session, the raw BiDi escape hatch, how stealth works, contributing back
- [interaction-skills/](interaction-skills/) : reusable mechanics (dialogs, tabs, cross-origin iframes, screenshots, connection)

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
- **Give each subagent its own session.** Tell a browser-using subagent to run every command with
  its own `BROWSER_SESSION=<name>` and to end with `browser stop <name>`, so concurrent work never
  shares a browser. `stop-all` is for cleaning up everything at once: it refuses while other
  sessions are live, and `--force` is for when you mean exactly that.
- **`daemon did not come up` at high concurrency is contention, not a broken install.** Concurrent
  session launches compete for CPU, so the startup wait scales itself up and the timeout error names
  the competing sessions. Stagger browser-using subagents, and use `http_get` or WebFetch for pages
  that render without a browser. Suspect a real fault only when a solo launch fails; the reason is
  in `/tmp/vesta-browser-<session>.log`.
- **`browser open` can land in an existing blank tab.** Some builds accept the BiDi connection but
  never answer `browsingContext.create`; after the bounded wait, `open` takes over an existing blank
  context instead and reports it in `# target_id`. Your page is loaded either way, so keep driving
  the reported context. If every command on the session wedges, `browser stop <session>` and
  relaunch once.
- **An intercepted click fails; trust the exit code over the page.** When an overlay sits on top of
  a ref (a consent banner is the classic), `browser click` exits non-zero naming the interceptor,
  because the page after such a click looks exactly like success while every control kept its
  default. Dismiss the overlay, take a fresh snapshot, click again, and verify the control changed
  (read the checked input) before trusting a value the page renders.
- **A wait that times out is usually a wrong sentinel, not a slow page.** Top-level `let`/`const`
  declarations are not `window` properties, so polling `window.<name>` never matches. Wait on rendered
  state instead (`wait_for_text`, a node count), and check the wait's exit code: no match exits 1.
- **A block on one route does not characterise the host.** A WAF can answer per route: on one site a
  `GET` of an HTML page returned 200 with a JS challenge page (`<title>Waiting</title>`) while a
  `POST` to its internal JSON API returned 403 with a block page. So "curl gets 403 here" and "curl
  gets 200 here" can both be true of the same host, and a single probe is not a verdict on whether
  the browser is needed.

## Auth-gated / heavy-JS pages

- **Heavy-JS auth pages (Google, Zoom, Apple `idmsa`/`dev.apple`, and similar SPAs) HANG `goto`/`wait_for_load` for the full timeout**: these SPAs keep network connections open so the `load` event never fires cleanly, yet the page almost always loaded underneath. After a `goto` that times out, do NOT retry it and NEVER call `wait_for_load()` on these. Run a SEPARATE short call (`timeout 30 browser`) that reads `page_info()` and inspects the DOM directly (no navigation, no wait_for_load). Cap every browser call at `timeout 40-55` so a hang costs seconds, not minutes. Long blocking browser calls during a live exchange make the agent go unresponsive, so keep them short.
- **Login-form fills need care**: some sign-in widgets live in an iframe (e.g. Apple's `aid-auth-widget-iFrame`, same-origin so `contentDocument` works). A JS `value`-set often does NOT satisfy the form's own validation (it re-renders back to empty after "Verifying..."), and real keystrokes (`type_text`) can DOUBLE a field that already holds a value, so CLEAR it first. These flows also commonly gate on device-2FA or a passcode that only the user's phone has, so browser automation frequently cannot finish them: prefer the official API or app path.
