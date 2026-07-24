# Connection & Sessions

## The daemon

Each `BROWSER_SESSION` runs one daemon holding a single WebDriver BiDi websocket to Camoufox.
The CLI talks to it over `/tmp/vesta-browser-<session>.sock`. `browser launch` starts Camoufox
and records its BiDi URL; the daemon connects on the next command via `ensure_daemon()`.

Unlike stock Chromium + CDP, there is no omnibox-popup / invisible-target problem: on connect the
daemon opens a session and adopts the first top-level browsing context, and `browsingContext.getTree`
only ever returns real contexts.

## Startup sequence

1. Check whether a daemon is already healthy (`daemon_healthy()` in `admin.py`).
2. If a stale socket exists but the daemon is dead, `ensure_daemon()` cleans it up and respawns.
3. `list_tabs()` shows the open contexts.
4. `ensure_real_tab()` switches to a real page if you're on an internal one.

```python
tab = ensure_real_tab()
goto("https://example.com")
```

## Recovering a wedged session

```bash
browser doctor        # Camoufox install + per-session daemon health
browser stop          # tear down this session's daemon + Camoufox + state files
browser launch        # fresh
```

Session state lives under `/tmp/vesta-browser-<session>.*` (`.sock`, `.pid`, `.bidi-ws`, `.log`).
`browser stop` cleans its own; `browser stop-all` clears every session.
