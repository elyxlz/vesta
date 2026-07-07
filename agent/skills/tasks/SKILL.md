---
name: tasks
description: Tasks, to-dos, reminders, time-based alerts; create and manage. Requires daemon.
---

# Tasks + Reminders - CLI: tasks

One CLI, one daemon, one SQLite DB. Tasks are what needs doing; reminders are nudges about when.

## Task Commands
```bash
tasks add "Buy groceries"
tasks add "Submit report" --priority high --due-in-hours 4
tasks add "Meeting prep" --due-datetime "2025-12-01T10:00:00" --timezone "Europe/London"
tasks list
tasks list --show-completed
tasks search "groceries"
tasks update <id> --status done
tasks update <id> --title "Updated title" --priority high
tasks get <id>
tasks get <id> --field status              # just the status, no envelope
tasks get <id> --field notes --field title # several fields, tab-separated
tasks delete <id>                          # CASCADE: linked reminders are deleted too
```

### Task Options
- `--priority`: low / normal / high (default: normal)
- `--due-in-minutes`, `--due-in-hours`, `--due-in-days`: relative due date
- `--due-datetime` + `--timezone`: absolute (both required together)
- `--show-completed`: include done tasks in list/search
- `--initial-metadata`: string of metadata to attach when adding a task
- `tasks list`, `tasks search`, and `tasks remind list` default to a compact tab-separated table; pass `--json` for one-line JSON or `--json-pretty` for indented JSON.
- `tasks get --field <name>` returns only the named field(s) as raw text. Valid fields: `id`, `title`, `status`, `priority`, `due_date`, `created_at`, `completed_at`, `metadata_path`, `metadata`. Prefer this over `Read`-ing `~/.tasks/metadata/<id>.md` when you only need a specific field. Metadata content is read only when `--field metadata` is requested.

## Reminder Commands

Reminders take the message as the first positional argument to `tasks remind`. There is no `create` subcommand, so don't reach for one:

```bash
# Set a reminder (the message IS the first argument, no subcommand needed)
tasks remind "Call mom" --in-minutes 30
tasks remind "Check report" --in-hours 2
tasks remind "Weekly review" --in-days 7
tasks remind "Meeting" --at "2025-12-01T10:00:00" --tz "Europe/London"

# Linked to a task
tasks remind "Check progress" --task <id> --in-hours 1

# Recurring
tasks remind "Standup" --recurring daily --at "2025-12-01T10:30:00" --tz "America/New_York"
tasks remind "Review" --recurring weekly --at "2025-12-06T17:00:00" --tz "America/New_York"
tasks remind "Bills" --recurring monthly --at "2025-12-15T09:00:00" --tz "America/New_York"
tasks remind "Birthday" --recurring yearly --at "2025-03-14T12:00:00" --tz "America/New_York"
tasks remind "Check inbox" --recurring hourly

# Recurring on a custom schedule (standard cron)
tasks remind "Weekdays 9am" --cron "0 9 * * 1-5" --tz "America/New_York"
tasks remind "Every 15 min, 9-5" --cron "*/15 9-17 * * *" --tz "America/New_York"
tasks remind "1st of the month" --cron "0 8 1 * *" --tz "America/New_York"

# List, delete, update
tasks remind list                        # all active reminders
tasks remind list --task <id>            # reminders linked to a task
tasks remind delete <id>                 # removes the reminder, task stays
tasks remind update <id> --message "New message"
```

### Reminder Options
- `--in-minutes`, `--in-hours`, `--in-days`: relative timing
- `--at` + `--tz`: absolute datetime (both required together)
- `--recurring`: hourly | daily | weekly | monthly | yearly
  - hourly needs no datetime; others require `--at` + `--tz`
- `--cron "<expr>"`: standard 5-field cron (`min hour day-of-month month day-of-week`) for schedules the presets can't express. Supports `*`, ranges (`1-5`), lists (`1,3,5`), steps (`*/15`), and day-of-week names (`mon-fri`). Day-of-week uses **standard cron numbering** (`0` or `7` = Sunday, `1` = Monday), so `--cron "0 9 * * 1-5"` fires 9am Mon-Fri as expected. Requires `--tz`; cannot combine with `--recurring`/`--at`/`--in-*`.
  - Both `--recurring` and `--cron` schedules are DST-aware: they store your IANA timezone and keep firing at the same wall-clock time across clock changes.
- Always use the user's timezone from MEMORY.md section 4, not UTC
- `--task <id>`: link reminder to a task (optional)
- `--message`: alternative to positional message argument

### Recurring Automations
Recurring reminders double as scheduled automations. The message is delivered as a notification:
```bash
tasks remind "Summarize week ahead" --recurring weekly --at "2025-12-01T08:00:00" --tz "Europe/London"
tasks remind "Archive completed tasks" --recurring weekly --at "2025-12-05T17:00:00" --tz "Europe/London"
tasks remind "Check inbox" --recurring hourly
```
When a recurring reminder fires, treat the message as an instruction and act on it.

## Behavior

### Auto-Generated Reminders
When a task has a due date, 4 auto-generated reminders are created:
- 1 week before due
- 1 day before due
- 1 hour before due
- 15 minutes before due

There is **no at-due fire**: when the due time itself is reached, no notification is emitted. If you want a fire at the exact due time (e.g. user says "remind me at 6pm to X"), set an explicit reminder with `tasks remind "X" --at "..." --tz "..."` instead of relying on `tasks add --due-datetime`.

These are skipped if the trigger time is already in the past. They are cleaned up when:
- The task is marked done (`--status done`)
- The task is deleted (FK cascade)
- They can also be individually deleted with `tasks remind delete <id>`

### Cascade Deletion
- Deleting a task deletes all linked reminders (FK ON DELETE CASCADE)
- Deleting a reminder does NOT affect the linked task

### Missed Reminders
When the daemon restarts, any one-time reminders that should have fired while the daemon was down are immediately sent as missed notifications.

### Notification Files
Written to the notifications directory as JSON:
- Reminder: `*-tasks-reminder.json` with type `reminder`
- Daemon death: `*-tasks-daemon_died.json` with type `daemon_died`

## Data
- SQLite DB: `~/.tasks/tasks.db`
- Task metadata files: `~/.tasks/metadata/<id>.md`
- Logs: `~/.tasks/logs/daemon.log`
- PID file: `~/.tasks/serve.pid`

## Setup
```bash
uv tool install ~/agent/skills/tasks/cli
```

## Background Daemon

Register with vestad to get a port (see [service](../service/SKILL.md)), then start:
```bash
PORT=$(~/agent/skills/service/scripts/register-service tasks)
screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications --port $PORT
```

One daemon handles everything, both task due-date monitoring and reminder scheduling. No separate reminder daemon needed.

**Restart**: Add this startup command to the `## Daemons` section of `~/agent/skills/restart/SKILL.md`:
```
PORT=$(~/agent/skills/service/scripts/register-service tasks) && screen -dmS tasks tasks serve --notifications-dir ~/agent/notifications --port $PORT
```

### Reminder Patterns
[User's common reminder types and preferences]
