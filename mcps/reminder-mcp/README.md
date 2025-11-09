# Reminder MCP

Time-based notification MCP for Vesta that creates scheduled reminders.

## Features

- Set one-time or recurring reminders
- Support for relative time (in X minutes/hours/days)
- Support for absolute datetime (ISO-8601)
- Recurring patterns: daily, hourly, weekly
- Automatic missed reminder detection
- Writes notifications to Vesta's notification directory

## Tools

- `set_reminder(message, datetime, seconds, minutes, hours, days, recurring, day_of_week, time)` - Schedule a reminder
- `list_reminders()` - List all active reminders
- `cancel_reminder(reminder_id)` - Cancel a reminder

## Examples

```python
# Remind in 30 minutes
set_reminder("Call mom", minutes=30)

# Daily reminder at 9:00 AM
set_reminder("Daily standup", recurring="daily", time="09:00")

# Weekly reminder every Monday at 9:00 AM
set_reminder("Weekly meeting", recurring="weekly", day_of_week="monday", time="09:00")

# Specific datetime
set_reminder("Doctor appointment", datetime="2024-01-15T14:30:00")

# Hourly reminder
set_reminder("Drink water", recurring="hourly")
```

## How it works

1. Uses APScheduler to manage timed jobs
2. When a reminder triggers, writes notification to `notifications/` directory
3. Vesta processes the notification on next run
4. On startup, checks for any missed reminders and fires them immediately
5. Scheduler runs as always-on MCP server
