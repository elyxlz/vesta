"""Unit tests for tasks_cli.format — compact renderers for list output."""

from tasks_cli import format as fmt


def test_format_task_list_empty():
    assert fmt.format_task_list([]) == "(no tasks)"


def test_format_task_list_columns_and_priority_label():
    tasks = [
        {
            "id": "t1",
            "title": "ship PR",
            "status": "pending",
            "priority": 3,
            "due_date": "2026-04-25T09:00:00+00:00",
        },
        {
            "id": "t2",
            "title": "water plants",
            "status": "done",
            "priority": 2,
            "due_date": None,
        },
    ]
    out = fmt.format_task_list(tasks)
    lines = out.splitlines()
    assert len(lines) == 2
    assert "pending" in lines[0]
    assert "high" in lines[0]
    assert "ship PR" in lines[0]
    assert "t1" in lines[0]
    assert "done" in lines[1]
    assert "norm" in lines[1]
    assert "-" in lines[1]  # no due date


def test_format_task_list_truncates_long_title():
    long = "x" * 200
    out = fmt.format_task_list([{"id": "t", "title": long, "status": "pending", "priority": 2}])
    assert "..." in out


def test_format_reminder_list_empty():
    assert fmt.format_reminder_list([]) == "(no reminders)"


def test_format_reminder_list_renders_fields_and_markers():
    reminders = [
        {
            "id": "r1",
            "task_id": "t1",
            "message": "follow up",
            "schedule": "once at 2026-04-25T09:00",
            "next_run": "2026-04-25T09:00:00+00:00",
            "auto_generated": True,
        },
        {
            "id": "r2",
            "task_id": None,
            "message": "call mom",
            "schedule": "daily at 09:00 UTC",
            "next_run": "2026-04-24T09:00:00+00:00",
            "auto_generated": False,
        },
    ]
    out = fmt.format_reminder_list(reminders)
    lines = out.splitlines()
    assert len(lines) == 2
    assert "r1" in lines[0]
    assert "follow up" in lines[0]
    assert " *" in lines[0]  # auto_generated marker
    assert "task=t1" in lines[0]
    assert "r2" in lines[1]
    assert "call mom" in lines[1]
    assert " *" not in lines[1]
    assert "task=" not in lines[1]
