---
name: hibob
description: Drive app.hibob.com's own internal web API as the already-logged-in user, exactly as the website does. Use for Bob HR data an ordinary employee can see but the public API and MCP server cannot expose - open to-do tasks, profile, company directory, org tree, time-off balance, personal documents. CLI: hibob.
---

# hibob (CLI: hibob)

Talks to `app.hibob.com/api/...` the way the website does: it runs
`fetch('/api/...', {credentials:'include'})` from inside the already-signed-in
browser page, so every call carries the user's real session cookie and returns exactly
what he sees in the UI. This is "the website, programmatically".

## Why this and not the alternatives

- **Public REST API** (`api.hibob.com/v1`) needs a service-user token created by a
  Bob **admin**. An ordinary employee has no admin rights -> route closed.
- **Bob MCP server** (`~/.hibob/token.json`, `hibob_oauth.py`) works for some tools
  but returns `403 exception.permissions.forbidden` on the task endpoints for a
  plain employee. It genuinely cannot see the signed-in employee's own open tasks.
- **The web UI can see all of it**, because the access rides the *session*, not an
  API key. So we drive the internal API from his logged-in browser page. Confirmed:
  `hibob tasks list` returns all 18 tasks the MCP server 403s on.

## Auth model

No credential is read, printed, or persisted by this tool. The session lives in the
Camoufox profile at `/root/.browser/profile` and is held by the `vesta_browser`
daemon; we only ask that already-authenticated page to make same-origin fetches.
Nothing is written under `~/.hibob/` by `hibob`. Because the fetch is **same-origin**,
the CLI first parks the active tab on `https://app.hibob.com/home` (a stray Google
SSO redirect on some pages would otherwise make the call cross-origin and the
browser would block it).

Prereq: a live browser session on that profile. If none is up:
```
browser launch --headless --user-data-dir /root/.browser/profile
browser navigate https://app.hibob.com/home
```
The CLI self-heals a dropped daemon via `admin.ensure_daemon()`; if the browser
itself is gone it fails loudly telling you to relaunch. The entry point runs under
the browser tool's own venv interpreter (its shebang), which is where the
`vesta_browser` package and its `websockets` dep live.

## Two Angular/BiDi traps (already handled in the code, do not "fix" them)

1. `helpers.js` wraps its argument in `( ... )`, so the fetch script must be a single
   **expression** (an IIFE), never multiple statements.
2. Bob is Angular; Zone.js replaces `window.Promise`, so returning a promise to
   BiDi's `awaitPromise` serialises a ZoneAwarePromise and crashes. The IIFE returns
   synchronously and the result is polled off `window.__hb`.

## Commands (every one verified against the live session on 2026-09-07)

`--json` on all of them; human-readable by default.

| Command | Output seen |
|---|---|
| `hibob whoami` | `<Display Name> <work email> id=<employee id> <Company> (<Job title>)` |
| `hibob me` | full profile: UK site, Europe/London, GBP, session=employee, isManager=no |
| `hibob tasks list [--status Open\|Closed\|all] [--limit N]` | the signed-in employee's open tasks, with due dates and task list |
| `hibob people search <substr>` | directory match, e.g. `Johan Nordberg <johan@elevenlabs.io> site=Italy -> Piotr Dabkowski` |
| `hibob org tree [--root <substr>] [--depth N]` | reporting tree built from `reportsTo`; verified multi-level under Piotr Dabkowski |
| `hibob timeoff balance` | Holiday + Sick policies, "Annual allowance: Unlimited", cycle 2026-01-01..12-31 |
| `hibob docs list` | Confidential Docs (4 PDFs incl. signed offer letter & NDA), Shared Docs (0) |

## Confirmed endpoints (method, path, body)

Employee id and company id come from `/api/user`. All observed by intercepting
the real pages (`/to-dos/my-tasks`, `/time-off/my-time-off`, `/docs/my-docs`).

- `GET  /api/user` -> 200, the logged-in identity.
- `GET  /api/company` -> 200, company profile.
- `GET  /api/employees/essentials` -> 200, **whole company directory** as a JSON
  array; each entry has `work.reportsTo` (id + displayName), used for people search
  and the org tree.
- `POST /api/tasks/types/general/{employeeId}` -> 200. **This is the key one.** Body:
  ```json
  {"viewSettings":{"limit":50,"offset":0,"orderBy":{"name":"dueDate","order":"desc"}},
   "filters":{"requestedFor":[],"taskList":[],"status":["Open"],
              "dueDate":{"type":"predefined","dateValue":"all_times"},
              "searchFor":"","groupIds":[]}}
  ```
  Returns `{"total":18,"tasks":[...]}`. `status` is `[]` for all, `["Open"]` or
  `["Closed"]` to filter.
- `GET  /api/timeoff/employees/{id}/balance/policies/summary-metrics` -> 200, balances.
- `GET  /api/docs/employees/{id}/folders?onboarding=false` -> 200, folder list.
- `GET  /api/docs/employees/{id}/folders/{folderId}/docs` -> 200, documents in folder.

## What did NOT work (verified, not assumed)

- `GET /api/tasks/types/general/{id}` -> **HTTP 404**. The my-tasks page calls this
  path but as a **POST** with the body above; the GET the URL suggests does not exist.
  The CLI's loud-error path was checked against exactly this: it raises
  `... -> HTTP 404` rather than returning an empty list.
- Bob **MCP** task tools -> `403 exception.permissions.forbidden` for this employee.
- Bob **public REST API** -> needs an admin-created service token; unavailable.
- On `/docs/my-docs` a `HEAD /api/docs/esign/templates` fires but is **not** the
  document list; the real list is the two `/api/docs/employees/{id}/folders...` calls
  above. Do not mistake the esign HEAD for the docs feed.
- Both hibob hosts sit behind Cloudflare, which 403s a bare urllib User-Agent with
  body `error code: 1010`. Not relevant to this CLI (calls run inside the browser),
  but it is why any out-of-browser call needs a real browser User-Agent.

## Failure behaviour

Any non-2xx raises with the status and response body (never a silent empty list). A
200 with an empty array (e.g. Shared Docs has 0 documents, `myGroupsWithSharedTasks`
returns `{"groups":[]}`) is a valid, distinct result and is shown as such.

## Daemon and notifications

```
hibob-daemon start | stop | restart | status     # registered in restart/daemons.sh
hibob-poll                                       # one pass by hand, safe to run anytime
```

`hibob-poll` runs every **15 minutes** and writes `source=hibob` notifications into
`~/agent/notifications/`:

| type | interrupt | fires when |
|---|---|---|
| `task_new` | yes | a task id appears that was not in state |
| `task_due_changed` | no | an existing task's due date moved |
| `task_due_today` | yes | a task crosses into due-today, once |
| `task_overdue` | yes | a task crosses into overdue, once |

**A first run notifies about NOTHING.** With no state file it records every open task
and stays silent, so installing this did not dump 18 onboarding tasks into his
intake. State lives at `~/agent/data/hibob/seen.json`.

**Failure is loud on purpose.** A dead browser session, a non-zero exit, empty stdout
with exit 0, or an unexpected payload shape all make the poll exit 1 with the reason.
It never reports "no tasks" for a pass that could not see anything, because a real
zero and a broken instrument are otherwise the same output, and only one of them is
worth acting on. Empty stdout with exit 0 is checked explicitly since that is the
exact shape of the fake zero this box has been burned by before.

**It is read-only.** It never marks, completes or writes anything in Bob, and it does
not notify when a task disappears, because that is the user completing it.

**Verified end to end on 7 Sep**: first run recorded 18 and notified nothing; deleting
one entry from state and re-polling produced exactly one `task_new` notification that
arrived in the agent's intake. That positive control matters more than the happy path,
because a watcher that cannot fire is indistinguishable from a quiet week.

## Writing: completing and reopening tasks (7 Sep 2026)

```
hibob complete <task_id>     # mark a task done
hibob reopen   <task_id>     # undo that
```

`POST /api/tasks/actions` with
`{"tasksAction":"complete"|"incomplete","taskDetailRequest":[{"taskType":"workflowToDoType","triggeredTaskId":<int>,"isScheduled":false}]}`,
answering `{"toDosUpdated": N}`. Task ids come from `hibob tasks list --json`.

**How the endpoint was found, because the method matters more than the URL.** The
Bob JS bundles yielded nothing greppable and the completion request could not be
observed without making one. So it was a **reversible probe**: complete one P3
(`[P3] Housekeeping`), watch the open count go 17 -> 16, immediately reopen it, and
confirm the count returns to 17 with the task present. Bob's own UI offers both
verbs, so the round trip is a supported operation rather than a hack, and the record
ends where it started.

**`toDosUpdated` is checked, not just the status code.** A 200 with zero rows updated
is a silent no-op and is exactly the failure that reads as success. A bogus id now
fails loudly: `HTTP 404 {"error":"some tasks weren't found"}`.

**Rule for using it:** only ever mark a task done that is ACTUALLY done. This writes
to his employer's HR record, and a task wrongly closed is worse than one left open,
because nothing downstream will ever ask about it again.
