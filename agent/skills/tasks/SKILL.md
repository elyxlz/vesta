---
name: tasks
description: This skill should be used when the user asks about "tasks", "to-do", "todo", "task list", "reminders", "remind me", "alert", "notify", or needs to create, manage, track, or organize tasks, to-do items, reminders, and time-based notifications. Everything actionable becomes a task immediately. All work, progress, drafts go in task metadata. Reminders are nudges about when to think about something, standalone or linked to a task. IMPORTANT: this skill requires a background daemon. Before doing anything, immediately make sure the daemon is running. Read this skill to learn how.
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
tasks delete <id>                # CASCADE: linked reminders are deleted too
```

### Task Options
- `--priority`: low / normal / high (default: normal)
- `--due-in-minutes`, `--due-in-hours`, `--due-in-days`: relative due date
- `--due-datetime` + `--timezone`: absolute (both required together)
- `--show-completed`: include done tasks in list/search
- `--initial-metadata`: string of metadata to attach when adding a task

## Reminder Commands

**IMPORTANT**: there is NO `create` subcommand. To set a reminder, put the message as the first argument directly:
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
- Always use the user's timezone from MEMORY.md section 5, not UTC
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
- Task due: `*-tasks-due.json` with type `task_due`
- Reminder: `*-tasks-reminder.json` with type `reminder`
- Daemon death: `*-tasks-daemon_died.json` with type `daemon_died`

## Data
- SQLite DB: `~/.tasks/tasks.db`
- Task metadata files: `~/.tasks/metadata/<id>.md`
- Logs: `~/.tasks/logs/daemon.log`
- PID file: `~/.tasks/serve.pid`

## Setup
```bash
uv tool install ~/vesta/agent/skills/tasks/cli
```

## Background Daemon

Register with vestad to get a port, then start:
```bash
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services \
  -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"tasks"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])")
screen -dmS tasks tasks serve --notifications-dir ~/vesta/notifications --port $PORT
```

One daemon handles everything, both task due-date monitoring and reminder scheduling. No separate reminder daemon needed.

**Restart**: Add to `~/vesta/agent/prompts/restart.md`:
```
PORT=$(curl -sk -X POST https://localhost:$VESTAD_PORT/agents/$AGENT_NAME/services -H "X-Agent-Token: $AGENT_TOKEN" -H 'Content-Type: application/json' -d '{"name":"tasks"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['port'])") && screen -dmS tasks tasks serve --notifications-dir ~/vesta/notifications --port $PORT
```

### Reminder Patterns
[User's common reminder types and preferences]
