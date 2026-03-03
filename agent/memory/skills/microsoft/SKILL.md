---
name: microsoft
description: This skill should be used when the user asks about "email", "emails", "inbox", "messages", "calendar", "schedule", "scheduling", "meetings", "appointments", "events", "outlook", or needs to read/send emails, manage calendar events, or handle time-based tasks via Microsoft/Outlook. IMPORTANT — this skill requires a background daemon. Before doing anything, immediately make sure the daemon is running. Read this skill to learn how.
---

# Microsoft — CLI: microsoft

## Setup

1. Create an Azure App Registration at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
   - Name: anything (e.g. "Vesta")
   - Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
   - Redirect URI: leave blank (device flow doesn't need one)
   - Under "API permissions", add: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`
   - Under "Authentication", enable "Allow public client flows"
2. Copy the **Application (client) ID**
3. Set environment variable:
   ```
   MICROSOFT_MCP_CLIENT_ID=<your-client-id>
   ```
4. Install: `uv tool install {install_root}/tools/microsoft`
5. Start background daemon: `microsoft serve &`

## Authentication

```bash
microsoft auth login                         # Start device flow — gives you a URL and code
microsoft auth complete --flow-cache <cache>  # Complete after signing in at the URL
microsoft auth list                           # List authenticated accounts
```

## Email

```bash
microsoft email list --account user@example.com
microsoft email get --account user@example.com --id <email_id>
microsoft email send --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks!"
microsoft email search --account user@example.com --query "project update"
```

## Calendar

```bash
microsoft calendar list --account user@example.com
microsoft calendar create --account user@example.com --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
microsoft calendar respond --account user@example.com --id <event_id> --response accept
```

## Notes
- `--account` required for all email/calendar commands (find with: `microsoft auth list`)
- `--timezone` required for calendar create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentativelyAccept
- `--to`/`--cc`/`--attendees` accept multiple space-separated values
- `--no-cancellation` on delete skips notifying attendees
- `--no-details` on calendar list returns compact output (no body/attendees)
- `--user-timezone` on calendar list converts times to the given IANA timezone
- `--folder` on email list/search filters by folder (default "inbox")
- `--no-attachments` on email get skips attachment metadata
- `--save-to` on email get saves the full email JSON to a file
- `--categories` on email update accepts multiple space-separated category names

## Background: `microsoft serve &`

### First Use — Data Gathering

On first activation with a new user, spend significant time analyzing their email and calendar data to learn their patterns. This is critical for being immediately useful:

1. **Read sent emails** (`email list --account <acct> --folder sentitems --limit 50`) — reveals writing style, tone, sign-offs, key contacts
2. **Read inbox** (`email list --account <acct> --limit 50`) — shows what they receive, subscriptions, who contacts them
3. **Read calendar** (`calendar list --account <acct>`) — schedule, recurring commitments, timezone
4. **Get full content** of important sent emails (`email get --account <acct> --id <id>`) — understand tone variations by recipient
5. **Update this skill file** — fill in every section below with what you learned
6. **Update MEMORY.md** — add any life details discovered (job, interests, contacts, location, relationships, etc.)

Be thorough. Read dozens of emails. The more context you gather now, the better you can draft emails in their voice, manage their calendar, and anticipate needs.

### Contact Communication Styles
[How to communicate with different contacts — fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns — fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone, which account for what]

### Scheduling Preferences
[User's scheduling patterns — fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments — fill in after data gathering: weekly/monthly recurring events, who with]
