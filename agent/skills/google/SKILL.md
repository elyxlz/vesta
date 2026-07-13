---
name: google
description: Google-native REST APIs (Gmail, Google Calendar) for users who bring their own Google Cloud OAuth client (~/.google/credentials.json required). For everyday email and calendar prefer the email-client skill, which needs no Google Cloud project. Requires daemon.
---

# Google, CLI: google

Official Google REST APIs (Gmail + Calendar v3), authenticated with **your own
Google Cloud OAuth client**: a `~/.google/credentials.json` is required, there is
no shared sign-in. Only reach for this skill when the user genuinely needs
Google-native APIs; for ordinary Gmail mail and calendar, the `email-client`
skill is the right choice (zero-setup sign-in, no Google Cloud project). Every
command prints JSON to stdout.

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS google google serve --notifications-dir ~/agent/notifications`

## Email (Gmail)

```bash
google email list
google email get --id <message_id>
google email send --to bob@example.com --subject "Hello" --body "Message"
google email reply --id <message_id> --body "Thanks!"
google email search --query "project update"
```

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
