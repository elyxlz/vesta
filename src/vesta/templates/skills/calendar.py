"""Calendar skill template."""

SKILL_MD = """\
---
name: calendar
description: This skill should be used when the user asks about "calendar", "schedule", "scheduling", "meetings", "appointments", "events", or needs to manage calendar events, respond to invitations, or handle time-based tasks.
---

# Calendar

You have access to calendar tools via the `microsoft` CLI. Use them to help the user manage their schedule.

## Setup

Install the CLI tool (if not already installed):
```bash
uv tool install {install_root}/clis/microsoft
```

## Commands

```bash
# List upcoming events (next 7 days)
microsoft list-events --account user@example.com

# List events with custom range
microsoft list-events --account user@example.com --days-ahead 14 --days-back 3

# List events from a specific calendar
microsoft list-events --account user@example.com --calendar-name "Work"

# List available calendars
microsoft list-calendars --account user@example.com

# Get event details
microsoft get-event --account user@example.com --id <event_id>

# Create an event
microsoft create-event --account user@example.com --subject "Team Standup" --start "2025-11-15T10:00:00" --end "2025-11-15T10:30:00" --timezone "Europe/London"

# Create with attendees and location
microsoft create-event --account user@example.com --subject "Lunch" --start "2025-11-15T12:00:00" --end "2025-11-15T13:00:00" --timezone "Europe/London" --location "Cafe" --attendees alice@example.com bob@example.com

# Create all-day event
microsoft create-event --account user@example.com --subject "Holiday" --start "2025-12-25" --timezone "Europe/London" --all-day

# Create recurring event
microsoft create-event --account user@example.com --subject "Weekly Sync" --start "2025-11-15T09:00:00" --end "2025-11-15T09:30:00" --timezone "Europe/London" --recurrence weekly --recurrence-end-date "2026-03-01"

# Update an event
microsoft update-event --account user@example.com --id <event_id> --subject "New Title" --start "2025-11-15T11:00:00" --timezone "Europe/London"

# Delete an event (sends cancellation to attendees)
microsoft delete-event --account user@example.com --id <event_id>

# Delete without sending cancellation
microsoft delete-event --account user@example.com --id <event_id> --no-cancellation

# Respond to an event invitation
microsoft respond-event --account user@example.com --id <event_id> --response accept
microsoft respond-event --account user@example.com --id <event_id> --response decline --message "Can't make it"
microsoft respond-event --account user@example.com --id <event_id> --response tentativelyAccept

# List authenticated accounts
microsoft list-accounts
```

## Background Monitoring

Start the monitor to get notifications for upcoming events:
```bash
microsoft serve &
```

## Best Practices

- Always check for conflicts before scheduling
- Include relevant details (location, attendees, agenda) when creating events
- Respect user's working hours and preferences
- Provide clear summaries of upcoming events

### Scheduling Preferences
[User's preferred meeting times, durations, buffer time]

### Regular Events
[Recurring meetings and commitments]
"""

SCRIPTS: dict[str, str] = {}
