# Advanced browser usage

Two things you reach for occasionally: running several browsers at once, and giving back what you
learn about a site.

## Parallel work

A session name is the isolation key: it selects the profile, the browser process, and the tabs a
program sees. Two programs sent to one session drive one browser, so they share tabs and can
navigate each other's pages. A session also runs one program at a time, so a second program on a
busy session is refused rather than queued.

Give every parallel task its own session name, and tell a subagent which name to use:

```bash
browser exec --session research-a <<'PY'
new_tab("https://a.example")
wait_for_load()
print(page_info())
PY
```

Each live browser costs several hundred MB, so three or more at once on a small host can exhaust
memory. Prefer one session at a time for a wide scrape, and end a burst of parallel work with
`browser session stop <name>` for each name you started, or one `browser stop-all`.

## Contribute back what you learn

When you work out something non-obvious about a site or a mechanic, contribute it through the
`upstream` skill before you finish. Two kinds:

1. **Domain skill** under `domain-skills/<host>/<topic>.md`: private APIs, stable selectors,
   framework quirks, URL patterns, waits, traps.
2. **Interaction skill** under `interaction-skills/<mechanic>.md`: a mechanic that repeats across
   sites, such as a new dialog pattern, a shadow-DOM trick, or an upload variant.

Keep three things out of both: pixel coordinates (they break on a different viewport, so describe
how to locate the target instead), narration of the task you just did, and any secret, cookie,
session token, or credential.
