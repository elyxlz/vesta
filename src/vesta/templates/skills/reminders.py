"""Reminders skill template."""

SKILL_MD = """\
---
name: reminders
description: This skill should be used when the user asks about "reminders", "remind me", "alert", "notify", or needs to set, manage, or check reminders and time-based notifications.
---

# Reminders

You have access to reminder tools via the `reminder` CLI. Use them to help the user set and manage reminders.

## Setup

Install the CLI tool (if not already installed):
```bash
uv tool install {install_root}/clis/reminder
```

## Commands

```bash
# Set a reminder in relative time
reminder set --message "Call the dentist" --in-minutes 30
reminder set --message "Submit report" --in-hours 2
reminder set --message "Renew subscription" --in-days 7

# Set a reminder at a specific time
reminder set --message "Team meeting" --scheduled-datetime "2025-11-15T10:00:00" --tz "Europe/London"

# Set a recurring reminder
reminder set --message "Take medication" --in-hours 1 --recurring daily
reminder set --message "Weekly review" --scheduled-datetime "2025-11-15T09:00:00" --tz "Europe/London" --recurring weekly

# List active reminders
reminder list
reminder list --limit 20

# Update a reminder's message
reminder update --id <reminder_id> --message "Updated message"

# Cancel a reminder
reminder cancel --id <reminder_id>
```

## Background Monitoring

Start the scheduler daemon to fire reminders on time:
```bash
reminder serve &
```

## Best Practices

- Always confirm the time and message before setting a reminder
- Use relative time (--in-minutes, --in-hours) for near-future reminders
- Use absolute time (--scheduled-datetime) for specific dates
- Include enough context in the message so it's useful when it fires

### Reminder Patterns
[User's common reminder types and preferences]
"""

SCRIPTS: dict[str, str] = {}
