---
name: google
description: This skill should be used when the user asks about "gmail", "google email", "google calendar", "gcal", "google meet", or needs to read/send emails via Gmail, manage Google Calendar events, create Google Meet links, or handle scheduling via Google. Requires a background daemon.
---

# Google - CLI: google

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS google google serve --notifications-dir ~/vesta/notifications`

## Email (Gmail)

```bash
google email list
google email get --id <message_id>
google email send --to bob@example.com --subject "Hello" --body "Message"
google email reply --id <message_id> --body "Thanks!"
google email search --query "project update"
```

## Calendar (Google Calendar)

```bash
google calendar list
google calendar create --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
google calendar respond --id <event_id> --response accept
```

## Meet (Google Meet)

```bash
google meet create                  # Create a standalone Meet link (no calendar event)
```

Use `--meet-link` on calendar create to attach a Meet link to an event instead.

## Notes
- No `--account` needed. Google CLI uses a single authenticated account
- Gmail uses `--label` (INBOX, SENT, DRAFT, etc.) instead of folders
- Calendar uses `--calendar` (defaults to "primary") for calendar selection
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentative
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list converts times to the given IANA timezone
- `--meet-link` on calendar create attaches a Google Meet video call link to the event
- `--no-notification` on calendar delete skips notifying attendees
- `--no-attachments` on email get skips attachment metadata
- `--save-to` on email get saves the full email JSON to a file

### Contact Communication Styles
[How to communicate with different contacts. Fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns. Fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone]

### Scheduling Preferences
[User's scheduling patterns. Fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments. Fill in after data gathering: weekly/monthly recurring events, who with]
