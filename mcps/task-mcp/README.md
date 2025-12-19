# Task MCP

Simple task management MCP for Vesta with priority tracking and due dates.

## Features

- Add tasks with priority levels (1-3)
- Set due dates with relative or absolute dates
- Mark tasks as done/pending
- Filter completed tasks
- Automatic sorting by priority and due date
- File-based metadata per task

## Tools

- `add_task(title, due, priority, initial_metadata)` - Create a new task
- `list_tasks(show_completed)` - List all tasks (includes `metadata_path`)
- `get_task(task_id)` - Get task with full metadata content
- `update_task(id, status, title, priority)` - Update task properties
- `delete_task(task_id)` - Delete task and its metadata file

## Metadata

Each task has a markdown file at `metadata_path`. To update metadata, use Read/Edit tools on this file.

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

# Create task with initial metadata
add_task("Research topic", initial_metadata="Keywords: AI, MCP")

# Get task with metadata content
task = get_task(task_id="abc12345")
# task["metadata_path"] = path to .md file
# task["metadata_content"] = file contents
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
