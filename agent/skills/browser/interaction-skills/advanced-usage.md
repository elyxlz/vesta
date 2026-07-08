# Advanced browser usage

Things you reach for occasionally: extending the helpers, running parallel sessions, the raw
protocol escape hatch, how stealth actually works, and contributing improvements back.

## Extending the helpers

Helpers are in `cli/src/vesta_browser/helpers.py`. The package is installed editable, so when you
edit that file the next `browser` call uses the new code without rebuilding. Add a helper when you
find yourself repeating the same BiDi dance. Keep it short.

```bash
$EDITOR ~/agent/skills/browser/cli/src/vesta_browser/helpers.py
# add your helper, save
browser <<'PY'
my_new_helper(...)   # already available
PY
```

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
`browser stop` cleans its own; `browser stop-all` stops everything. Memory warning: each Camoufox
uses several hundred MB, so 3+ concurrently on a small host can OOM. Prefer sequential for
wide-scrape tasks.

## Raw BiDi escape hatch

Anything not wrapped by a helper:

```bash
browser bidi "browsingContext.getTree"
browser bidi "storage.setCookie" '{"cookie":{"name":"k","value":"v","domain":"example.com"}}'
browser bidi "script.evaluate" '{"expression":"1+1","awaitPromise":true}'
```

Or from stdin mode: `bidi("storage.getCookies", filter={"domain": "example.com"})`. The daemon
injects the current `context` (or `target`) where the command shape needs one. Over a connected
Chrome (see remote-control.md) the same BiDi verbs are translated to CDP, so the escape hatch
still works, but browser-specific methods (Firefox-only or Chrome-only) will not cross over.

## How stealth works

Camoufox spoofs the fingerprint (navigator, screen, WebGL, timezone, fonts,
`navigator.webdriver=false`) in patched Gecko C++, below anything JS can observe, so it survives
the CreepJS-tier `Function.prototype.toString` / descriptor / stack-frame battery that stock
Chromium + CDP injection cannot. Each profile draws one coherent fingerprint preset (`presets.py`),
stable across restarts and distinct across profiles. There is no `--stealth` flag to toggle and no
Xvfb to provision; headless is the stealthy default.

## Contribute back what you learn

If you figured out something non-obvious about a site or mechanic, or wrote a broadly useful
helper, contribute it upstream before you finish via the `upstream-pr` skill. Three kinds, in
order of frequency:

1. **Domain skill** under `domain-skills/<host>/<topic>.md`. Private APIs, stable selectors,
   framework quirks, URL patterns, waits, traps.
2. **Interaction skill** under `interaction-skills/<mechanic>.md`. Reusable mechanics (a new
   dialog pattern, a shadow-DOM trick, an upload variant).
3. **New helper in `helpers.py`** when the primitive is broadly useful. Filter: would every other
   Vesta benefit, or is this a personal quirk? Upstream if generic; keep it local (in a
   `domain-skills/` recipe) if site- or user-specific.

What *not* to put anywhere shared: pixel coordinates (they break on viewport/zoom; describe how to
locate the target instead), narration of the specific task you just did, or secrets / cookies /
session tokens / personal credentials.

Flow: edit locally (takes effect immediately via `uv tool install --editable`), verify, then use
the `upstream-pr` skill to open a PR to `elyxlz/vesta`.
