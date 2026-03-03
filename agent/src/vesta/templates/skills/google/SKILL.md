---
name: google
description: This skill should be used when the user asks about "gmail", "google email", "google calendar", "gcal", "google meet", or needs to read/send emails via Gmail, manage Google Calendar events, create Google Meet links, or handle scheduling via Google.
---

# Google — CLI: google

## Setup

1. Go to https://console.cloud.google.com/ and create a project (or use an existing one)
2. Enable the **Gmail API**, **Google Calendar API**, and **Google Meet REST API** under "APIs & Services" > "Library"
3. Go to "APIs & Services" > "Credentials" > "Create Credentials" > "OAuth client ID"
   - Application type: **Desktop app**
   - Download the JSON file
4. Place the credentials file at `~/data/google/credentials.json`
5. Install: `uv tool install {install_root}/tools/google`
6. Start background daemon: `google serve &`

## Authentication

```bash
google auth login                   # Start OAuth flow — gives you a URL to visit
google auth complete --code <code>  # Complete after authorizing and pasting the code from redirect URL
google auth login-local             # Alternative: runs local server to handle redirect automatically
google auth list                    # Show authenticated account
```

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
- No `--account` needed — Google CLI uses a single authenticated account
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

## Background: `google serve &`

### First Use — Data Gathering

On first activation with a new user, spend significant time analyzing their email and calendar data to learn their patterns. This is critical for being immediately useful:

1. **Read sent emails** (`email list --label SENT --limit 50`) — reveals writing style, tone, sign-offs, key contacts
2. **Read inbox** (`email list --limit 50`) — shows what they receive, subscriptions, who contacts them
3. **Read calendar** (`calendar list`) — schedule, recurring commitments, timezone
4. **Get full content** of important sent emails (`email get --id <id>`) — understand tone variations by recipient
5. **Update this skill file** — fill in every section below with what you learned
6. **Update MEMORY.md** — add any life details discovered (job, interests, contacts, location, relationships, etc.)

Be thorough. Read dozens of emails. The more context you gather now, the better you can draft emails in their voice, manage their calendar, and anticipate needs.

### Contact Communication Styles
[How to communicate with different contacts — fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns — fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone]

### Scheduling Preferences
[User's scheduling patterns — fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments — fill in after data gathering: weekly/monthly recurring events, who with]
