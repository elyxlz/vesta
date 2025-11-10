# Task MCP

Simple task management MCP for Vesta with priority tracking and due dates.

## Features

- Add tasks with priority levels (1-3)
- Set due dates with relative or absolute dates
- Mark tasks as done/pending
- Filter completed tasks
- Automatic sorting by priority and due date
- Optional metadata field for extensibility

## Tools

- `add_task(title, due, priority, metadata)` - Create a new task
- `list_tasks(show_completed)` - List all tasks
- `update_task(id, status, title, metadata, priority)` - Update task properties

## Examples

```python
# Add a high priority task due tomorrow
add_task("Finish project report", due="tomorrow", priority=3)

# Add a normal priority task with no due date
add_task("Review pull requests", priority=2)

# List only pending tasks (default)
list_tasks()

# List all tasks including completed
list_tasks(show_completed=True)

# Mark task as done
update_task(id="abc12345", status="done")

# Change priority
update_task(id="abc12345", priority=3)

# Add metadata
add_task("Research topic", metadata="Keywords: AI, MCP")
```

## Priority Levels

- `1` - Low priority
- `2` - Normal priority (default)
- `3` - High priority

Tasks are automatically sorted by:
1. Priority (high to low)
2. Due date (soonest first, no-due-date at end)
3. Created date (newest first)

## Due Date Formats

- `"today"` - Today's date
- `"tomorrow"` - Tomorrow's date
- `"in 3 days"` - 3 days from now
- `"2024-01-15"` - Specific date (YYYY-MM-DD)

## How it works

- Pure CRUD operations (Create, Read, Update, Delete)
- No background jobs or scheduling
- SQLite database for persistence
- Status tracking: pending → done
- Completion timestamp automatically set when marked done
