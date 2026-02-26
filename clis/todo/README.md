# Todo CLI

Simple todo management CLI for Vesta with priority tracking and due dates.

## Features

- Add todos with priority levels (1-3)
- Set due dates with relative or absolute dates
- Mark todos as done/pending
- Filter completed todos
- Automatic sorting by priority and due date
- File-based metadata per todo
- Background monitor for due date notifications

## Commands

```bash
todo add "Buy groceries"
todo add "Submit report" --priority high --due-in-hours 4
todo list
todo list --show-completed
todo get <id>
todo update <id> --status done
todo update <id> --title "New title" --priority high
todo delete <id>
todo search "groceries"
todo serve   # background monitor for due date notifications
```

## Priority Levels

- `1` / `low` - Low priority
- `2` / `normal` - Normal priority (default)
- `3` / `high` - High priority

Todos are automatically sorted by:
1. Priority (high to low)
2. Due date (soonest first, no-due-date at end)
3. Created date (newest first)
