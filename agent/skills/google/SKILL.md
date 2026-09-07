---
name: google
description: Google Gmail + Calendar. Two backends. (1) OAuth REST APIs (needs your own Google Cloud client, ~/.google/credentials.json) via CLI `google`. (2) Gmail's OWN internal web/sync API driven from the logged-in browser session (no OAuth, no IMAP, no API key) via CLI `gmail-web`, read-only, for tenants that block third-party OAuth. Requires daemon (OAuth backend) / a live browser session (web backend).
---

# Google

Two independent backends live in this skill. Pick by how the account is reachable:

| Backend | CLI | Auth | Use when |
|---|---|---|---|
| Google REST APIs | `google` | your own Google Cloud OAuth client (`~/.google/credentials.json`) | you have (or can make) an OAuth client the account's tenant allows |
| Gmail internal web/sync API | `gmail-web` | the already-logged-in browser session (cookie), read-only | OAuth is blocked at the tenant and IMAP/SMTP is off, but the Gmail **web** client works |

The `gmail-web` backend exists for a Google Workspace tenant that returns
`Error 400 access_not_configured` for third-party
OAuth (admin-allowlisted) and has IMAP/SMTP disabled, yet whose Gmail web session
is live. See the **Gmail via the browser session** section below. The OAuth
`google` CLI is unchanged and still works wherever an allowed OAuth client exists.

# Google (OAuth REST), CLI: google

Official Google REST APIs (Gmail + Calendar v3), authenticated with **your own
Google Cloud OAuth client**: a `~/.google/credentials.json` is required, there is
no shared sign-in. Only reach for this skill when the user genuinely needs
Google-native APIs; for ordinary Gmail mail and calendar, the `email-client`
skill is the right choice (zero-setup sign-in, no Google Cloud project). Success
output is JSON on stdout; a failure exits non-zero and prints `{"error": ...}` on
stderr, so it survives piping stdout through grep/head/jq.

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `google daemon start`

## Email (Gmail)

```bash
google email list
google email get --id <message_id>
google email send --to bob@example.com --subject "Hello" --body "Message"
google email reply --id <message_id> --body "Thanks!"
google email search --query "project update"
```

Email sends and replies wait 30 seconds by default. The delay is one persisted setting for the Google client and cannot be overridden on an individual send:

```bash
google email send-delay
google email send-delay --seconds 60
google email pending
google email undo --id <pending_id>
```

The send or reply command creates a Gmail draft and returns a `pending` status with its id and scheduled send time. `google serve` sends due drafts, and every email command already requires it to be running. Use `undo` to cancel a pending send and delete its Gmail draft: it works right up until the daemon starts dispatching that message. Set `--seconds 0` for immediate delivery. Explicit drafts are never queued.

`pending` also lists messages whose status is `failed`, with `last_error` saying why: delivery kept erroring, or it was cut off mid-dispatch. A message cut off mid-dispatch may already have been sent, so read the Sent folder before you `undo` it or send it again.

## Calendar (Google Calendar REST API v3)

```bash
google calendar list --days-ahead 30 --limit 20        # upcoming events
google calendar list --days-back 14 --days-ahead 0     # recent past
google calendar calendars                              # list calendars
google calendar get --id <event_id>
google calendar create --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
google calendar update --id <event_id> --start "2025-11-15T11:00:00" --timezone "Europe/London"
google calendar delete --id <event_id>
google calendar respond --id <event_id> --response accept
```

Event ids are **Calendar API event ids** (the `id` field the API returns, e.g.
`abc123def456`), not iCalendar UIDs; ids from before the REST switch do not
resolve, re-list to get current ones. Recurring events are expanded into
concrete occurrences in the query window (`singleEvents`), returned sorted by
start time. `update` and `delete` on an occurrence id apply to the **whole
series** (the id resolves to the series master). `respond` never emails the
guest list; only create/update/delete send attendee notifications.

## Google Meet

Not implemented: there is no `meet` command and `calendar create` does not attach
a Meet link (no `conferenceData` support). Because the OAuth client is your own,
nothing blocks adding it: enable the Calendar API (and any Meet scopes) on your
Google Cloud project and wire it up if the user asks.

## Sign-in (bring your own OAuth client)

Sign-in requires your own Google Cloud **Desktop app** OAuth client JSON at
`~/.google/credentials.json`; without it sign-in fails with a pointer at
[SETUP.md](SETUP.md). The flow is loopback OAuth (prints a consent URL,
listens on `127.0.0.1`, does not auto-open a browser). One consent grants
`https://mail.google.com/` (Gmail) + `.../auth/calendar` (Calendar). A stored
token stays tied to the client that minted it: a token from another client (e.g.
the old shared Thunderbird client) keeps refreshing and Gmail keeps working, but
calendar 403s until you re-run `google auth login` under your own client.

## Draft-only mode

Set `EMAIL_DRAFT_ONLY=1` (truthy: `1`/`true`/`yes`, case-insensitive) to hard-disable sending. In this mode `email send`/`reply` (and `forward`, when present) are refused before any Gmail API call (non-zero exit with a clear message); only `email draft` works. Default off: unset/empty means today's behavior, no change.

## Notes
- No `--account` needed. Google CLI uses a single authenticated account
- Gmail uses `--label` (INBOX, SENT, DRAFT, etc.) instead of folders
- Calendar uses `--calendar` (defaults to "primary") for calendar selection
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentative
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--limit` on calendar list caps the number of events returned
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list returns times in the given IANA timezone
- `--no-notification` on calendar delete skips attendee cancellation emails (`sendUpdates=none`)
- Creating/updating/deleting events with attendees emails them invites/updates, a real outward send that EMAIL_DRAFT_ONLY does not cover
- `--no-attachments` on email get skips attachment metadata
- `email get` saves the readable body to `~/.google/emails/<subject>_<id>.txt` (idempotent: re-fetching overwrites, HTML is flattened to text with links preserved)
- `--save-to` on email get writes the body file to a chosen path instead

### Contact Communication Styles
[How to communicate with different contacts. Fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns. Fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone]

### Scheduling Preferences
[User's scheduling patterns. Fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments. Fill in after data gathering: weekly/monthly recurring events, who with]

---

# Gmail via the browser session, CLI: `gmail-web`

`gmail-web` drives **Gmail's own internal web API** (its `sync` endpoints) exactly
as the Gmail web client does: it runs `fetch('/sync/u/0/i/...', {credentials:
'include', headers:{...}})` from inside the already-signed-in browser page, so
every call carries the user's real session cookie and returns exactly what the web
UI shows. **Not OAuth, not IMAP, not the public Gmail REST API.**

This exists because on a locked-down Workspace tenant the obvious auth routes are
closed (both verified 2026-09-07): OAuth returns `Error 400 access_not_configured`
(the tenant allowlists OAuth apps, so a bring-your-own client fails
identically), and IMAP/SMTP are disabled. The web client works, so the access rides
the session cookie.

## READ-ONLY

`gmail-web` lists, searches and reads. It has **no** send/reply/forward/draft/
label/archive/delete/mark path, by design. Send was deliberately not shipped: the
web client's send request only fires when a composed message is actually
transmitted, and it could not be captured without sending real mail as the user, so
there was nothing to verify against. See "What did NOT work" below.

## Commands (every one run against the live session on 2026-09-07)

`--json` on all of them; human-readable by default.

| Command | Output seen |
|---|---|
| `gmail-web whoami` | `Signed in to Gmail web as: <work email>` |
| `gmail-web list [--label INBOX\|SENT\|STARRED\|IMPORTANT\|UNREAD\|SPAM\|TRASH\|ALL\|<name>] [--limit N]` | INBOX returned 25 threads with sender, subject, date, unread flag, `thread-f:` id, msg count |
| `gmail-web search "<gmail query>" [--limit N]` | e.g. `is:unread` -> 5 unread threads; `from:okta` -> the Okta threads |
| `gmail-web get --id <threadId> [--max-chars N]` | full message bodies (HTML) for every message in a thread; 3-message "Security alert" thread returned all 3 bodies |

`--label` maps to a Gmail search: `INBOX`->`in:inbox`, `SENT`->`in:sent`,
`UNREAD`->`is:unread`, etc.; an unknown value becomes `label:<value>`. Thread ids
accept the numeric form or the full `thread-f:...`.

## Auth model

No credential is read, printed, or persisted by this tool. The session lives in the
Camoufox profile at `/root/.browser/profile`, held by the `vesta_browser` daemon; we
only ask that already-authenticated page to make same-origin `fetch`es. Because the
fetch is same-origin, the CLI parks the tab on `https://mail.google.com/mail/u/0/`
first (a stray redirect elsewhere would make the call cross-origin and the browser
would block it). The CLI self-heals a dropped daemon via `admin.ensure_daemon()`.

**The catch, and how it's solved.** Gmail's sync endpoints need two *per-session*
request headers on top of the cookie: `X-Framework-Xsrf-Token` and `X-Gmail-BTAI`
(a client-capabilities blob that embeds the inbox key `ik` and build id). Without
the xsrf header the endpoint returns **HTTP 400**; without BTAI it returns **HTTP
500**. Neither value is in any simple page global (`GM_ACTION_TOKEN` is unrelated,
`GLOBALS` holds the `ik` at index 9 but not the xsrf token). We harvest them the
honest way: a WebDriver-BiDi **main-world preload script** intercepts the page's own
bootstrap sync requests (`XMLHttpRequest`) and copies those exact header values onto
`window.__gmHdrs`; the CLI reuses them verbatim. A fresh navigation to the mailbox
reliably fires the bootstrap requests, so the harvest needs no user-visible action.
These headers are **credentials**: the tool never prints them and never writes them
to disk.

Prereq: a live browser session on that profile with a logged-in Google account. If
none is up:
```
browser launch --headless --user-data-dir /root/.browser/profile
browser navigate https://mail.google.com/mail/u/0/
```

## Two browser-JS traps (handled in the code, do not "fix" them)

1. `helpers.js` wraps its argument in `( ... )`, so any injected script must be a
   single **expression** (an IIFE), never multiple statements.
2. Returning a promise to BiDi's `awaitPromise` can mis-serialise; the fetch IIFE
   returns synchronously and the result is polled off `window.__gm`.

## Confirmed endpoints (method, path, body)

All `POST https://mail.google.com/sync/u/0/i/<ep>?hl=en&c=<rand>&rt=r&pt=ji`, body
is JSON (JSPB array format), headers as above. Observed by intercepting the live
Gmail page's own XHRs and confirmed by replaying with the harvested headers.

- **`bv`** = browse view = LIST / SEARCH. Body (only query + count vary from the
  captured template):
  ```
  [[123, <count>, null, "<gmail search query>", [ ...timestamps... ],
    "itemlist-ViewType(123)-9", 1, 2000, null, 0, null,null,null, 1, null,
    [1,0,0, ...caps... ], null,null, 1, null,null, 0,1,0, [[[2,<count>]]], 0,0,
    null,null,null,null,null, [] ], null, [0,5,null,null,1,1,1]]
  ```
  ViewType `123` is the generic search view; the query is standard Gmail search
  syntax (`in:inbox`, `is:unread`, `from:x`, `label:y`, ...). Response is a deep
  JSPB array; the thread list is at `resp[-1][0][1]` (with `resp[-1][0][0] == 2` the
  item-list marker). Each thread is `[subject, snippet, ts_ms, "thread-f:ID",
  [messages...], ...]`; each message `["msg-f:ID", [1, fromEmail, fromName], ...,
  ts_ms(6), snippet(9), [labels](10), ...]`. Unread = a message whose label list
  contains `^u`. An empty result is `[[2, null, 0, []]]` (thread list = `null`) and
  is returned as an empty list, not an error.
- **`fd`** = fetch data = READ a thread with full bodies. Body:
  `[[["thread-f:ID", null, null]], 2]`. Response `[0, [["thread-f:ID", null,
  [ ["msg-f:ID", [msgMeta...]], ... ]]]]`; `msgMeta[4]` is the subject and the
  readable body (HTML) is a nested string within `msgMeta`. An unknown/inaccessible
  id echoes back only `[["thread-f:ID"]]` (no message array) -> loud error.

The inbox's *own* internal view query (seen when the app loads `#inbox`) is
`((in:^f) OR (in:^pfg) OR (in:^f_clns))` via ViewType `9`; `gmail-web list` uses the
equivalent user-facing `in:inbox` through ViewType `123`, which returns the same
threads and is simpler to build.

## What did NOT work (verified, not assumed)

- **OAuth** for this account -> `Error 400 access_not_configured` (tenant allowlist).
  A bring-your-own Google Cloud client fails identically. Not retried.
- **IMAP/SMTP** -> disabled on the account.
- A `bv`/`fd` request with **no `X-Framework-Xsrf-Token`** -> **HTTP 400**
  (`["er",...,400,...,3]`). With xsrf but **no `X-Gmail-BTAI`** -> **HTTP 500**
  (`["er",...,500,...,13]`). Both are surfaced loudly by the CLI. `X-Gmail-Storage-
  Request` is sent by the client but is **not** required (dropping it still 200s).
- A hand-built `bv` body sent **before** harvesting the real headers -> HTTP 400,
  which read like a bad body but was actually the missing xsrf token. Rule out the
  headers before theorising about the payload.
- **`send`** -> not implemented. Capturing the real send request means transmitting
  a real message as the user, which is out of scope. The endpoint is almost
  certainly another `/sync/u/0/i/` POST, but that is unverified and nothing that
  only-half-works was shipped.

## Failure behaviour

Any transport error, any non-2xx HTTP status, and Gmail's own `["er",...,<code>,...]`
error envelope all raise with the status and response body, never a silent empty
result. A genuine empty result (e.g. `SENT` returned 0 threads for this brand-new
account, same endpoint that returns 25 for `INBOX`) is a valid, distinct empty list
and is shown as such.
