"""Tasks skill template."""

SKILL_MD = """\
---
name: tasks
description: This skill should be used when the user asks about "tasks", "to-do", "todo", "task list", or needs to create, manage, track, or organize tasks and to-do items.
---

# Tasks

You have access to task management via the `task` CLI. Use it to help the user track and organize their tasks.

## Setup

Install the CLI tool (if not already installed):
```bash
uv tool install {install_root}/clis/task
```

## Commands

```bash
# Add a task
task add --title "Buy groceries"
task add --title "Submit report" --priority high
task add --title "Review PR" --due-in-hours 4
task add --title "Pay rent" --due-in-days 3 --priority high
task add --title "Meeting prep" --due-datetime "2025-11-15T09:00:00" --timezone "Europe/London"

# List tasks
task list
task list --show-completed

# Get a specific task
task get --id <task_id>

# Update a task
task update --id <task_id> --status completed
task update --id <task_id> --title "Updated title"
task update --id <task_id> --priority high

# Delete a task
task delete --id <task_id>

# Search tasks
task search --query "groceries"
task search --query "report" --show-completed
```

## Background Monitoring

Start the monitor to get notifications for due tasks:
```bash
task serve &
```

## Best Practices

- Use priorities (low/normal/high) to help the user focus
- Set due dates for time-sensitive tasks
- Mark tasks as completed when done, don't delete them
- Search before adding to avoid duplicates

### Task Patterns
[User's common task categories and workflows]
"""

SCRIPTS: dict[str, str] = {}
