"""Microsoft skill template (email + calendar via Microsoft Graph)."""

SKILL_MD = """\
---
name: microsoft
description: This skill should be used when the user asks about "email", "emails", "inbox", "messages", "calendar", "schedule", "scheduling", "meetings", "appointments", "events", "outlook", or needs to read/send emails, manage calendar events, or handle time-based tasks via Microsoft/Outlook.
---

# Microsoft — CLI: microsoft

## Setup

1. Create an Azure App Registration at https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
   - Name: anything (e.g. "Vesta")
   - Supported account types: "Accounts in any organizational directory and personal Microsoft accounts"
   - Redirect URI: leave blank (device flow doesn't need one)
   - Under "API permissions", add: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`
   - Under "Authentication", enable "Allow public client flows"
2. Copy the **Application (client) ID** and optionally the **Directory (tenant) ID**
3. Set environment variables:
   ```
   MICROSOFT_MCP_CLIENT_ID=<your-client-id>
   MICROSOFT_MCP_TENANT_ID=<your-tenant-id>  # optional, defaults to "common"
   ```
4. Install: `uv tool install {install_root}/clis/microsoft`
5. Start background daemon: `microsoft serve &`

## Authentication

```bash
microsoft auth login                         # Start device flow — gives you a URL and code
microsoft auth complete --flow-cache <cache>  # Complete after signing in at the URL
microsoft auth list                           # List authenticated accounts
```

## Email

### Quick Reference
```bash
microsoft email list --account user@example.com
microsoft email get --account user@example.com --id <email_id>
microsoft email send --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks!"
microsoft email search --account user@example.com --query "project update"
```

### Other Commands
```bash
microsoft email list --account user@example.com --folder "Sent Items" --limit 20
microsoft email get --account user@example.com --id <email_id> --no-attachments --save-to /tmp/email.json
microsoft email send --account user@example.com --to bob@example.com --cc alice@example.com --subject "Report" --body "See attached" --attachments /path/to/file.pdf
microsoft email reply --account user@example.com --id <email_id> --body "Noted" --reply-all
microsoft email draft --account user@example.com --to bob@example.com --subject "Draft" --body "WIP"
microsoft email attachment --account user@example.com --email-id <email_id> --attachment-id <att_id> --save-path /tmp/file.pdf
microsoft email search --account user@example.com --query "report" --folder "Sent Items" --limit 20
microsoft email update --account user@example.com --id <email_id> --is-read true
microsoft email update --account user@example.com --id <email_id> --categories "Important" "Follow Up"
```

## Calendar

### Quick Reference
```bash
microsoft calendar list --account user@example.com
microsoft calendar create --account user@example.com --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
microsoft calendar respond --account user@example.com --id <event_id> --response accept
```

### Other Commands
```bash
microsoft calendar list --account user@example.com --days-ahead 14 --days-back 3
microsoft calendar list --account user@example.com --calendar-name "Work" --no-details --user-timezone "America/New_York"
microsoft calendar calendars --account user@example.com
microsoft calendar get --account user@example.com --id <event_id>
microsoft calendar create --account user@example.com --subject "Lunch" --start "2025-11-15T12:00:00" --end "2025-11-15T13:00:00" --timezone "Europe/London" --location "Cafe" --body "Discuss project" --attendees alice@example.com bob@example.com
microsoft calendar create --account user@example.com --subject "Holiday" --start "2025-12-25" --timezone "Europe/London" --all-day
microsoft calendar create --account user@example.com --subject "Weekly Sync" --start "2025-11-15T09:00:00" --end "2025-11-15T09:30:00" --timezone "Europe/London" --recurrence weekly --recurrence-end-date "2026-03-01"
microsoft calendar update --account user@example.com --id <event_id> --subject "New Title" --start "2025-11-15T11:00:00" --timezone "Europe/London"
microsoft calendar delete --account user@example.com --id <event_id>
microsoft calendar respond --account user@example.com --id <event_id> --response decline --message "Can't make it"
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
