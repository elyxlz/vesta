---
name: reminders
description: This skill should be used when the user asks about "reminders", "remind me", "alert", "notify", or needs to set, manage, or check reminders and time-based notifications. Reminders are for the user, but also for yourself — use them to follow up, check in, or bring something up later. Tasks are the ground truth of what needs doing; reminders are nudges about when to think about it. IMPORTANT — this skill requires a background daemon. Before doing anything, immediately make sure the daemon is running. Read this skill to learn how.
---

# Reminders — CLI: reminder

## Quick Reference
```bash
reminder set "Call the dentist" --in-minutes 30
reminder set "Submit report" --in-hours 2
reminder set "Meeting" --scheduled-datetime "2025-11-15T10:00:00" --tz "Europe/London"
reminder set "Take meds" --in-hours 1 --recurring daily
reminder list --limit 20
reminder cancel <id>
reminder update <id> --message "Updated"
```

## Time Options
- Relative: `--in-minutes`, `--in-hours`, `--in-days`
- Absolute: `--scheduled-datetime` + `--tz` (both required together)
- Recurring: `--recurring` hourly|daily|weekly|monthly|yearly
  - hourly: no datetime needed; others: require `--scheduled-datetime` + `--tz`
  - Fires repeatedly at the interval from the scheduled time

## Recurring Automations
Recurring reminders double as scheduled automations. The reminder message is delivered as a notification, so use it to trigger any repeating workflow:
- `reminder set "Summarize my week ahead" --scheduled-datetime "2025-11-17T08:00:00" --tz "Europe/London" --recurring weekly` — every Monday morning briefing
- `reminder set "Archive completed tasks" --scheduled-datetime "2025-11-14T17:00:00" --tz "Europe/London" --recurring weekly` — Friday cleanup
- `reminder set "Check inbox" --recurring hourly` — periodic email check
- `reminder set "Review budget spreadsheet" --scheduled-datetime "2025-11-01T09:00:00" --tz "Europe/London" --recurring monthly`

When a recurring reminder fires, treat the message as an instruction and act on it.

## Setup: `uv tool install ~/vesta/skills/reminders/cli`
## Background: `screen -dmS reminder reminder serve --notifications-dir ~/vesta/notifications`

### Reminder Patterns
[User's common reminder types and preferences]
