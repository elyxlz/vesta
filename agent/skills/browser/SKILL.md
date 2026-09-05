---
name: browser
description: Drive a real browser: interactive sites, pages behind a sign-in, JavaScript-rendered content, filling and submitting forms, and screenshots of a page. Reach for it when an HTTP fetch returns markup without the content, when the page needs clicks or typing, or when the user asks to see a page. Add stealth when the user asks for it, or on concrete evidence that ordinary Chromium automation is rejected: a block page, a challenge that never clears, or a body that stays empty while the screenshot shows the page.
---

# Browser (CLI: browser)

## Choose a mode

Standard mode runs Chromium. `--stealth` runs Camoufox, an anti-detection Firefox. Start in
standard mode and keep it there while the site answers. Move to stealth when the user asks for it,
or on evidence that the site rejects standard automation: a block page, a challenge that never
clears, or a body that stays empty while the screenshot shows the page.

The two engines share nothing: no session, no tab, no cookie, no profile. A session keeps the
engine of its first call, so `--stealth` on a standard session answers `session_engine_conflict`.
Give a stealth run its own session name.

## Run one program

Write Python, send it on stdin, and read the one JSON line the command prints:

```bash
browser exec --session <name> [--stealth] [--timeout <secs>] <<'PY'
new_tab("https://example.com")
wait_for_load()
print(page_info())
PY
```

Put as much of one operation as practical in one program. Browser state persists by session (tabs,
cookies, the signed-in profile); Python variables do not, because each program runs with fresh
globals. Carry a value between programs by printing it and reading it back from `output.stdout`.

`--session` defaults to `default`. Use one session per account and one per parallel task, named in
lowercase letters, digits, `-`, and `_`. A session runs one program at a time. A session idle for
30 minutes stops its browser, and the next program starts it again on the same profile.

`--timeout` is the program's budget in seconds: 120 by default, 5 minimum, 600 maximum. Raise the
Bash tool timeout together with it, or the tool call ends while the program is still running.

## Helpers on both engines

Both engines bind the same 20 helpers, so a program written to this list runs on either:

- Navigation: `new_tab(url="about:blank")`, `goto_url(url)`, `wait_for_load(timeout=15.0)`
- Tabs: `list_tabs(include_chrome=True)`, `current_tab()`, `switch_tab(target, activate=False)`, `close_tab(target=None)`, `ensure_real_tab()`
- Input: `click_at_xy(x, y, button="left", clicks=1)`, `type_text(text)`, `fill_input(selector, text, clear_first=True, timeout=0.0)`, `press_key(key, modifiers=0)`, `scroll(x, y, dy=-300, dx=0)`
- Read and wait: `page_info()`, `js(expression, target_id=None)`, `wait(seconds=1.0)`, `wait_for_element(selector, timeout=10.0, visible=False)`, `wait_for_network_idle(timeout=10.0, idle_ms=500)`
- Files: `capture_screenshot(path=None, full=False, max_dim=None)`, `upload_file(selector, path)`

`js` returns the value of the expression, so read the page with it and print what you need. A tab
`target` is the `target_id` of a `list_tabs` or `current_tab` entry. `press_key` takes modifiers as
a bitmask: 1 Alt, 2 Control, 4 Meta, 8 Shift.

## Engine escape hatches

Chromium adds `cdp(method, **params)` for a raw DevTools call, plus `http_get`, `iframe_target`,
`activate_tab`, `dispatch_key`, and `drain_events`. Camoufox adds `page` and `context`, the
Playwright objects.

One engine's extension on the other answers `engine_capability_mismatch`. Two ways out: rewrite the
program with the portable helpers, or start a session under a new name on the engine that carries
the call. Never rerun the same program in the other engine to escape this error, because that
engine holds different cookies and a different profile.

## Read the result

Read `ok` first. On `ok: false`, read `error`: `code`, `phase`, `message`, `retryable`, and
`suggested_action`. Do what `suggested_action` says. On `ok: true`, read:

- `session`: `name`, `mode`, `engine`, `state`.
- `page`: where the browser stands after the program, as `url`, `title`, `tab_id`.
- `output`: `stdout` holds what the program printed, plus `stderr`, `exit_code`, `duration_ms`.
- `artifacts`: one entry per screenshot the program wrote, with `path`, `mime_type`, `bytes`.
- `warnings`: anything the daemon repaired or clamped.

A screenshot is a file on disk, not an image you have seen. Read the `path` with the Read tool to
look at it. A success prints the line on stdout; a failure prints it on stderr and exits 1.

## Handover

Hand the browser to the user when the wall is account trust: a sign-in the user must complete, a
locked tenant, a code that only their own device holds.

```bash
browser handover start --session <name> --url "<sign-in URL>" --minutes 30
```

Send the `data.user_url` from the answer to the user, alone. That URL is the whole handover: a
port, a local address, or a screenshot of the page helps nobody. The link lives for `--minutes`
(30 by default, 240 at most). `browser handover status` reports the state while the user works.

Run `browser handover stop` as soon as the user reports they are done, and confirm it answered.
The sign-in stays in that session's profile, so continue with `browser exec` on the same session
name. `browser exec` on a handed-over session answers `handover_in_use` until the handover stops.

## Recovery

- `browser doctor`: one report of binaries, versions, sessions, artifacts, handover readiness, and the last error.
- `browser engines`: which mode routes to which engine, and whether each engine is ready.
- `browser sessions`: every session and its state. `browser session stop <name>` stops one, `browser stop-all` stops all.
- `error.code` of `daemon_down`: run `browser daemon start`, then rerun the program. `browser daemon status|restart|stop` handle the rest.
- Installation and paths: [SETUP.md](SETUP.md).

## Recipes

Search these before inventing an approach to a site. They are optional references, so read the one
that matches and skip the rest.

- [interaction-skills/](interaction-skills/): mechanics that repeat across sites (clicking, tabs, dialogs, cross-origin iframes, screenshots, rich-text editors, Cloudflare challenges).
- [domain-skills/](domain-skills/): one directory per host, holding selectors, private APIs, URL patterns, and the traps found there.

```bash
ls ~/agent/skills/browser/domain-skills/amazon/
rg "<selector or keyword>" ~/agent/skills/browser/domain-skills/ ~/agent/skills/browser/interaction-skills/
```

Many sites answer their own JSON endpoints with everything the page shows, so check for that first:
one `curl` can replace a session, a navigation, and a read.
