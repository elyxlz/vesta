---
name: google
description: Gmail and Google Calendar: email, events, scheduling. Requires daemon.
---

# Google, CLI: google

Gmail runs on the Gmail REST API; Google Calendar runs on **CalDAV** (the REST
Calendar API is disabled for the shared sign-in client, see SETUP.md). Every
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

## Calendar (Google Calendar, via CalDAV)

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

Event ids are the iCalendar UID (e.g. `abc123@google.com`). Recurring events are
expanded into concrete occurrences in the query window. `list` returns events
sorted by start time.

## Google Meet

Meet is **not available** under the shared sign-in. Standalone Meet spaces need a
restricted scope the client is not verified for, and the calendar `conferenceData`
path needs the Calendar REST API, which is disabled for this client. Creating an
event does not attach a Meet link. (A separately-verified own Google Cloud app via
`~/.google/credentials.json` would be required to add Meet back, not wired up.)

## Sign-in (zero bring-your-own-app)

Default sign-in reuses **Thunderbird's published public OAuth client**, no Google
Cloud project, no `credentials.json`. It is a loopback OAuth flow (prints a consent
URL, listens on `127.0.0.1`, does not auto-open a browser). One verified consent
grants `https://mail.google.com/` (Gmail) + `.../auth/calendar` (used by CalDAV).
Drop a `~/.google/credentials.json` to use your own app instead (optional). A daily
daemon probe self-heals a dead upstream client automatically and only bothers you
as a last resort, run `google auth probe` to check health on demand. See
[SETUP.md](SETUP.md) for the full self-heal ladder.

## Draft-only mode

Set `EMAIL_DRAFT_ONLY=1` (truthy: `1`/`true`/`yes`, case-insensitive) to hard-disable sending. In this mode `email send`/`reply` (and `forward`, when present) are refused before any Gmail API call (non-zero exit with a clear message); only `email draft` works. Default off: unset/empty means today's behavior, no change.

## Notes
- No `--account` needed. Google CLI uses a single authenticated account
- Gmail uses `--label` (INBOX, SENT, DRAFT, etc.) instead of folders
- Calendar uses `--calendar` (defaults to "primary") for calendar selection
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentative
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--limit` on calendar list caps the number of events returned (after sorting)
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list converts times to the given IANA timezone
- `--no-notification` on calendar delete is accepted but a no-op under CalDAV (Google always notifies attendees)
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
