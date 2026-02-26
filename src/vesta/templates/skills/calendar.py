"""Calendar skill template."""

SKILL_MD = """\
---
name: calendar
description: This skill should be used when the user asks about "calendar", "schedule", "scheduling", "meetings", "appointments", "events", or needs to manage calendar events, respond to invitations, or handle time-based tasks.
---

# Calendar — CLI: microsoft

## Quick Reference
```bash
microsoft list-events --account user@example.com
microsoft create-event --account user@example.com --subject "Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"
microsoft respond-event --account user@example.com --id <event_id> --response accept
```

## Other Commands
```bash
microsoft list-events --account user@example.com --days-ahead 14 --days-back 3
microsoft list-events --account user@example.com --calendar-name "Work"
microsoft list-calendars --account user@example.com
microsoft get-event --account user@example.com --id <event_id>
microsoft create-event --account user@example.com --subject "Lunch" --start "2025-11-15T12:00:00" --end "2025-11-15T13:00:00" --timezone "Europe/London" --location "Cafe" --attendees alice@example.com bob@example.com
microsoft create-event --account user@example.com --subject "Holiday" --start "2025-12-25" --timezone "Europe/London" --all-day
microsoft create-event --account user@example.com --subject "Weekly Sync" --start "2025-11-15T09:00:00" --end "2025-11-15T09:30:00" --timezone "Europe/London" --recurrence weekly --recurrence-end-date "2026-03-01"
microsoft update-event --account user@example.com --id <event_id> --subject "New Title" --start "2025-11-15T11:00:00" --timezone "Europe/London"
microsoft delete-event --account user@example.com --id <event_id>
microsoft respond-event --account user@example.com --id <event_id> --response decline --message "Can't make it"
```

## Notes
- `--timezone` required for create/update (IANA names like "Europe/London")
- `--response` choices: accept / decline / tentativelyAccept
- `--account` required for all commands (find with: `microsoft list-accounts`)
- `--no-cancellation` on delete skips notifying attendees

## Setup: `uv tool install {install_root}/clis/microsoft`
## Background: `microsoft serve &`

### Scheduling Preferences
[User's preferred meeting times, durations, buffer time]

### Regular Events
[Recurring meetings and commitments]
"""

SCRIPTS: dict[str, str] = {}
