# Scheduler MCP

Simple scheduler MCP for Vesta that creates timed notifications.

## Features

- Set reminders with specific time or minutes from now
- Set alarms with simple time format (e.g., "09:30")
- List active reminders
- Cancel reminders
- Writes notifications to Vesta's notification directory

## Tools

- `set_reminder(message, time_str, minutes)` - Schedule a reminder
- `set_alarm(time_str, message)` - Set an alarm (simpler interface)
- `list_reminders()` - List all active reminders
- `cancel_reminder(reminder_id)` - Cancel a reminder

## Examples

```python
# Remind in 30 minutes
set_reminder("Call mom", minutes=30)

# Set alarm for specific time
set_alarm("09:30", "Morning standup")

# Schedule for specific datetime
set_reminder("Doctor appointment", time_str="2024-01-15T14:30:00")
```

## How it works

1. Uses APScheduler to manage timed jobs
2. When a reminder/alarm triggers, writes notification to `notifications/` directory
3. Vesta processes the notification on next run
4. Scheduler runs as always-on MCP server