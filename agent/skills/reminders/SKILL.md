---
name: reminders
description: Reminders are now part of the tasks CLI. Use `tasks remind` instead. This skill redirects to the tasks skill for all reminder functionality.
---

# Reminders — now part of Tasks CLI

Reminders have been unified into the tasks CLI. Use `tasks remind` instead of the old `reminder` command.

## Quick Reference
```bash
tasks remind "Call mom" --in-minutes 30
tasks remind "Check report" --task <id> --in-hours 1
tasks remind "Standup" --recurring daily --at "2025-12-01T10:30:00" --tz "UTC"
tasks remind list
tasks remind list --task <id>
tasks remind delete <id>
tasks remind update <id> --message "Updated"
```

## Full Documentation
See the tasks skill: `~/vesta/skills/tasks/SKILL.md`

## Daemon
The tasks daemon handles reminders. No separate reminder daemon needed:
```bash
screen -dmS tasks tasks serve --notifications-dir ~/vesta/notifications
```

Stop the old reminder daemon if still running:
```bash
screen -XS reminder quit
```
