---
name: microsoft
description: This skill should be used when the user asks about "email", "emails", "inbox", "messages", "calendar", "schedule", "scheduling", "meetings", "appointments", "events", "outlook", or needs to read/send emails, manage calendar events, or handle time-based tasks via Microsoft/Outlook. Requires a background daemon.
---

# Microsoft - CLI: microsoft

**Setup**: See [SETUP.md](SETUP.md)
**Background**: `screen -dmS microsoft microsoft serve --notifications-dir ~/notifications`

## Email

```bash
microsoft email list --account user@example.com
microsoft email get --account user@example.com --id <email_id>
microsoft email send --account user@example.com --to bob@example.com --subject "Hello" --body "Message"
microsoft email reply --account user@example.com --id <email_id> --body "Thanks!"
microsoft email search --account user@example.com --query "project update"
```

## Email Block/Unblock

Block or unblock senders to filter unwanted emails:

```bash
microsoft email block --account user@example.com --sender spam@example.com
microsoft email unblock --account user@example.com --sender spam@example.com
microsoft email block --account user@example.com --list  # show blocked senders
```

If block returns 403, re-authorize:
```bash
microsoft auth add --account user@example.com
```

## Calendar

```bash
microsoft calendar list --account user@example.com --days-ahead 7
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
- `--save-to` on email get saves the email body text to a file (NOT JSON, plain text only)
- `--categories` on email update accepts multiple space-separated category names

## Email Attachments

```bash
microsoft email attachment --account user@example.com --email-id '<email_id>' --attachment-id '<attachment_id>' --save-path /tmp/file.pdf
```

### Contact Communication Styles
[How to communicate with different contacts. Fill in after data gathering: who are the key contacts, what tone/formality for each, language preferences]

### Email Preferences
[User's email patterns. Fill in after data gathering: greeting style, sign-offs, capitalization, punctuation habits, typical length, tone, which account for what]

### Scheduling Preferences
[User's scheduling patterns. Fill in after data gathering: preferred meeting times, timezone, how they reschedule, buffer preferences]

### Regular Events
[Recurring meetings and commitments. Fill in after data gathering: weekly/monthly recurring events, who with]
