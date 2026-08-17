"""Unit tests for reminders_cli.format — compact renderer for reminder list output."""

from reminders_cli import format as fmt


def test_format_reminder_list_renders_fields():
    assert fmt.format_reminder_list([]) == "(no reminders)"
    reminders = [
        {
            "id": "r1",
            "message": "follow up",
            "schedule": "once at 2026-04-25T09:00",
            "next_run": "2026-04-25T09:00:00+00:00",
        },
        {
            "id": "r2",
            "message": "call mom",
            "schedule": "daily at 09:00 UTC",
            "next_run": "2026-04-24T09:00:00+00:00",
        },
    ]
    lines = fmt.format_reminder_list(reminders).splitlines()
    assert "r1" in lines[0] and "follow up" in lines[0]
    assert "r2" in lines[1] and "call mom" in lines[1]


def test_format_reminder_list_marks_fired_rows():
    reminders = [
        {"id": "r1", "message": "already ran", "schedule": "once", "next_run": None, "status": "completed"},
        {"id": "r2", "message": "not yet", "schedule": "once", "next_run": "2026-04-25T09:00:00+00:00", "status": "pending"},
    ]
    lines = fmt.format_reminder_list(reminders).splitlines()
    assert "[fired]" in lines[0]
    assert "[fired]" not in lines[1]
