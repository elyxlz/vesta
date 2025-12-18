"""Calendar skill template."""

SKILL_MD = """\
---
name: calendar
description: This skill should be used when the user asks about "calendar", "schedule", "scheduling", "meetings", "appointments", "events", or needs to manage calendar events, respond to invitations, or handle time-based tasks.
---

# Calendar

You have access to calendar tools through MCP. Use them to help the user manage their schedule.

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
