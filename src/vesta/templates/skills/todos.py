"""Todos skill template."""

SKILL_MD = """\
---
name: todos
description: This skill should be used when the user asks about "tasks", "to-do", "todo", "task list", or needs to create, manage, track, or organize tasks and to-do items.
---

# Todos — CLI: todo

## Quick Reference
```bash
todo add "Buy groceries"
todo add "Submit report" --priority high --due-in-hours 4
todo list
todo search "groceries"
todo update <id> --status done
todo update <id> --title "Updated title" --priority high
todo get <id>
todo delete <id>
```

## Options
- `--priority`: low / normal / high (default: normal)
- `--due-in-minutes`, `--due-in-hours`, `--due-in-days`: relative due date
- `--due-datetime` + `--timezone`: absolute (both required together)
- `--show-completed`: include done tasks in list/search
- `--initial-metadata`: JSON string of metadata to attach when adding a task

## Setup: `uv tool install {install_root}/clis/todo`
## Background: `todo serve &`

### Task Patterns
[User's common task categories and workflows]
"""

SCRIPTS: dict[str, str] = {}
