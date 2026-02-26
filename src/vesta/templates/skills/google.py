"""Google skill template (Gmail + Google Calendar)."""

SKILL_MD = """\
---
name: google
description: This skill should be used when the user asks about "gmail", "google email", "google calendar", "gcal", or needs to read/send emails via Gmail, manage Google Calendar events, or handle scheduling via Google.
---

# Google — CLI: google

## Setup

1. Go to https://console.cloud.google.com/ and create a project (or use an existing one)
2. Enable the **Gmail API** and **Google Calendar API** under "APIs & Services" > "Library"
3. Go to "APIs & Services" > "Credentials" > "Create Credentials" > "OAuth client ID"
   - Application type: **Desktop app**
   - Download the JSON file
4. Place the credentials file at `~/data/google/credentials.json`
5. Install: `uv tool install {install_root}/clis/google`
6. Start background daemon: `google serve &`

## Authentication

```bash
google auth login                   # Start OAuth flow — gives you a URL to visit
google auth complete --code <code>  # Complete after authorizing and pasting the code from redirect URL
google auth login-local             # Alternative: runs local server to handle redirect automatically
google auth list                    # Show authenticated account
```

## Email (Gmail)

### Quick Reference
```bash
google email list
google email get --id <message_id>
google email send --to bob@example.com --subject "Hello" --body "Message"
google email reply --id <message_id> --body "Thanks!"
google email search --query "project update"
```

### Other Commands
```bash
google email list --label INBOX --limit 20
google email get --id <message_id> --no-attachments --save-to /tmp/email.json
google email send --to bob@example.com --cc alice@example.com --subject "Report" --body "See attached" --attachments /path/to/file.pdf
google email reply --id <message_id> --body "Noted" --reply-all
google email draft --to bob@example.com --subject "Draft" --body "WIP"
google email attachment --email-id <message_id> --attachment-id <att_id> --save-path /tmp/file.pdf
google email search --query "report" --label SENT --limit 20
google email update --id <message_id> --add-labels IMPORTANT --remove-labels UNREAD
```

## Calendar (Google Calendar)

### Quick Reference
```bash
google calendar list
google calendar create --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
google calendar respond --id <event_id> --response accept
```

### Other Commands
```bash
google calendar list --days-ahead 14 --days-back 3
google calendar list --calendar "Work" --no-details --user-timezone "America/New_York"
google calendar calendars
google calendar get --id <event_id> --calendar "Work"
google calendar create --subject "Lunch" --start "2025-11-15T12:00:00" --end "2025-11-15T13:00:00" --timezone "Europe/London" --location "Cafe" --body "Discuss project" --attendees alice@example.com bob@example.com
google calendar create --subject "Holiday" --start "2025-12-25" --timezone "Europe/London" --all-day
google calendar create --subject "Weekly Sync" --start "2025-11-15T09:00:00" --end "2025-11-15T09:30:00" --timezone "Europe/London" --recurrence weekly --recurrence-end-date "2026-03-01"
google calendar update --id <event_id> --calendar "Work" --subject "New Title" --start "2025-11-15T11:00:00" --timezone "Europe/London"
google calendar delete --id <event_id> --no-notification
google calendar respond --id <event_id> --calendar "Work" --response decline --message "Can't make it"
```

## Notes
- No `--account` needed — Google CLI uses a single authenticated account
- Gmail uses `--label` (INBOX, SENT, DRAFT, etc.) instead of folders
- Calendar uses `--calendar` (defaults to "primary") for calendar selection
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentative
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list converts times to the given IANA timezone
- `--no-notification` on calendar delete skips notifying attendees
- `--no-attachments` on email get skips attachment metadata
- `--save-to` on email get saves the full email JSON to a file

## Background: `google serve &`

### Contact Communication Styles
[How to communicate with different contacts]

### Email Preferences
[User's preferred email handling patterns]

### Scheduling Preferences
[User's preferred meeting times, durations, buffer time]

### Regular Events
[Recurring meetings and commitments]
"""

SCRIPTS: dict[str, str] = {}
