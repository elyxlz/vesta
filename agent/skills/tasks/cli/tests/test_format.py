"""Unit tests for tasks_cli.format — compact renderers for list output."""

from tasks_cli import format as fmt


def test_format_task_list():
    assert fmt.format_task_list([]) == "(no tasks)"
    tasks = [
        {"id": "t1", "subject": "ship PR", "status": "pending", "priority": 3, "due_date": "2026-04-25T09:00:00+00:00"},
        {"id": "t2", "subject": "water plants", "status": "completed", "priority": 2, "due_date": None},
    ]
    lines = fmt.format_task_list(tasks).splitlines()
    assert "pending" in lines[0] and "high" in lines[0] and "ship PR" in lines[0] and "t1" in lines[0]
    assert "completed" in lines[1] and "norm" in lines[1] and "-" in lines[1]


def test_format_task_list_marks_parked_tasks():
    """A parked task is the one the digest stops naming, so the list is the only place left that
    says it exists. It must stay visible and it must say it is parked."""
    tasks = [
        {"id": "t1", "subject": "waiting on legal", "status": "pending", "priority": 2, "due_date": None, "backburner": 1},
        {"id": "t2", "subject": "ship PR", "status": "pending", "priority": 2, "due_date": None, "backburner": 0},
    ]
    lines = fmt.format_task_list(tasks).splitlines()
    assert lines[0].endswith("[parked] waiting on legal")
    assert lines[1].endswith("ship PR")
    assert "[parked]" not in lines[1]
