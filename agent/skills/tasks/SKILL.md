---
name: tasks
description: This skill should be used when the user asks about "tasks", "to-do", "todo", "task list", or needs to create, manage, track, or organize tasks and to-do items. Everything actionable becomes a task immediately. All work, progress, drafts go in task metadata. IMPORTANT — this skill requires a background daemon. Before doing anything, immediately make sure the daemon is running. Read this skill to learn how.
---

# Tasks — CLI: tasks

## Quick Reference
```bash
tasks add "Buy groceries"
tasks add "Submit report" --priority high --due-in-hours 4
tasks list
tasks search "groceries"
tasks update <id> --status done
tasks update <id> --title "Updated title" --priority high
tasks get <id>
tasks delete <id>
```

## Options
- `--priority`: low / normal / high (default: normal)
- `--due-in-minutes`, `--due-in-hours`, `--due-in-days`: relative due date
- `--due-datetime` + `--timezone`: absolute (both required together)
- `--show-completed`: include done tasks in list/search
- `--initial-metadata`: JSON string of metadata to attach when adding a task

## Setup: `uv tool install ~/vesta/skills/tasks/cli`
## Background: `screen -dmS tasks tasks serve --notifications-dir ~/vesta/notifications`

### Task Patterns
[User's common task categories and workflows]
