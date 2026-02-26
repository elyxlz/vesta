"""Tasks skill template."""

SKILL_MD = """\
---
name: tasks
description: This skill should be used when the user asks about "tasks", "to-do", "todo", "task list", or needs to create, manage, track, or organize tasks and to-do items.
---

# Tasks — CLI: task

## Quick Reference
```bash
task add "Buy groceries"
task add "Submit report" --priority high --due-in-hours 4
task list
task search "groceries"
task update <id> --status completed
task get <id>
task delete <id>
```

## Options
- `--priority`: low / normal / high (default: normal)
- `--due-in-minutes`, `--due-in-hours`, `--due-in-days`: relative due date
- `--due-datetime` + `--timezone`: absolute (both required together)
- `--show-completed`: include done tasks in list/search

## Setup: `uv tool install {install_root}/clis/task`
## Background: `task serve &`

### Task Patterns
[User's common task categories and workflows]
"""

SCRIPTS: dict[str, str] = {}
