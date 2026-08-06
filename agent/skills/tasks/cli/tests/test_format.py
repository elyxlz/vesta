"""Unit tests for tasks_cli.format — compact renderers for list output."""

from tasks_cli import format as fmt


def test_format_task_list():
    assert fmt.format_task_list([]) == "(no tasks)"
    tasks = [
        {"id": "t1", "title": "ship PR", "status": "pending", "priority": 3, "due_date": "2026-04-25T09:00:00+00:00"},
        {"id": "t2", "title": "water plants", "status": "done", "priority": 2, "due_date": None},
    ]
    lines = fmt.format_task_list(tasks).splitlines()
    assert "pending" in lines[0] and "high" in lines[0] and "ship PR" in lines[0] and "t1" in lines[0]
    assert "done" in lines[1] and "norm" in lines[1] and "-" in lines[1]


def test_format_task_list_marks_parked_tasks():
    """A parked task is the one the digest stops naming, so the list is the only place left that
    says it exists. It must stay visible and it must say it is parked."""
    tasks = [
        {"id": "t1", "title": "waiting on legal", "status": "pending", "priority": 2, "due_date": None, "backburner": 1},
        {"id": "t2", "title": "ship PR", "status": "pending", "priority": 2, "due_date": None, "backburner": 0},
    ]
    lines = fmt.format_task_list(tasks).splitlines()
    assert lines[0].endswith("[parked] waiting on legal")
    assert lines[1].endswith("ship PR")
    assert "[parked]" not in lines[1]


def test_format_reminder_list_renders_fields_and_markers():
    assert fmt.format_reminder_list([]) == "(no reminders)"
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
    lines = fmt.format_reminder_list(reminders).splitlines()
    assert "r1" in lines[0] and "follow up" in lines[0] and " *" in lines[0] and "task=t1" in lines[0]
    assert "r2" in lines[1] and " *" not in lines[1] and "task=" not in lines[1]
