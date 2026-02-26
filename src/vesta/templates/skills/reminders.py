"""Reminders skill template."""

SKILL_MD = """\
---
name: reminders
description: This skill should be used when the user asks about "reminders", "remind me", "alert", "notify", or needs to set, manage, or check reminders and time-based notifications.
---

# Reminders — CLI: reminder

## Quick Reference
```bash
reminder set "Call the dentist" --in-minutes 30
reminder set "Submit report" --in-hours 2
reminder set "Meeting" --scheduled-datetime "2025-11-15T10:00:00" --tz "Europe/London"
reminder set "Take meds" --in-hours 1 --recurring daily
reminder list
reminder cancel <id>
reminder update <id> --message "Updated"
```

## Time Options
- Relative: `--in-minutes`, `--in-hours`, `--in-days`
- Absolute: `--scheduled-datetime` + `--tz` (both required together)
- Recurring: `--recurring` hourly|daily|weekly|monthly|yearly
  - hourly: no datetime needed; others: require `--scheduled-datetime` + `--tz`

## Setup: `uv tool install {install_root}/clis/reminder`
## Background: `reminder serve &`

### Reminder Patterns
[User's common reminder types and preferences]
"""

SCRIPTS: dict[str, str] = {}
