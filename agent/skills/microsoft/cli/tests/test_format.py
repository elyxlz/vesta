"""Unit tests for microsoft_cli.format — compact renderers + @odata stripper."""

from microsoft_cli import format as fmt


def test_strip_odata_removes_top_and_nested_keys():
    data = {
        "@odata.context": "https://graph.microsoft.com/v1.0/$metadata",
        "value": [
            {"@odata.etag": "W/abc", "id": "1", "subject": "hi"},
            {"id": "2", "from": {"emailAddress": {"@odata.type": "#x", "address": "a@b.c"}}},
        ],
    }
    cleaned = fmt.strip_odata(data)
    assert "@odata.context" not in cleaned
    assert cleaned["value"][0] == {"id": "1", "subject": "hi"}
    assert cleaned["value"][1]["from"]["emailAddress"] == {"address": "a@b.c"}


def test_format_email_list_empty():
    assert fmt.format_email_list([]) == "(no messages)"


def test_format_email_list_columns_and_unread_marker():
    emails = [
        {
            "id": "AAA123",
            "subject": "Hello world",
            "from": {"emailAddress": {"address": "alice@example.com"}},
            "receivedDateTime": "2026-04-24T09:00:00Z",
            "isRead": False,
        },
        {
            "id": "BBB456",
            "subject": "Read already",
            "from": {"emailAddress": {"address": "bob@example.com"}},
            "receivedDateTime": "2026-04-23T08:00:00Z",
            "isRead": True,
        },
    ]
    out = fmt.format_email_list(emails)
    lines = out.splitlines()
    assert len(lines) == 2
    assert "alice@example.com" in lines[0]
    assert "Hello world" in lines[0]
    assert " *" in lines[0]  # unread marker
    assert "AAA123" in lines[0]
    assert " *" not in lines[1]
    assert "BBB456" in lines[1]


def test_format_email_list_handles_missing_fields():
    out = fmt.format_email_list([{"id": "x"}])
    # no crash, id present
    assert "x" in out


def test_format_email_list_truncates_long_subject():
    long = "s" * 200
    out = fmt.format_email_list([{"id": "1", "subject": long}])
    assert "..." in out
    assert len(out.split("\t")[2]) <= 80


def test_format_calendar_event_list_empty():
    assert fmt.format_calendar_event_list([]) == "(no events)"


def test_format_calendar_event_list_renders_times_and_location():
    events = [
        {
            "id": "evt1",
            "subject": "Standup",
            "start": {"dateTime": "2026-04-24T09:00:00"},
            "end": {"dateTime": "2026-04-24T09:30:00"},
            "location": {"displayName": "Zoom"},
        }
    ]
    out = fmt.format_calendar_event_list(events)
    assert "2026-04-24T09:00:00" in out
    assert "2026-04-24T09:30:00" in out
    assert "Standup" in out
    assert "Zoom" in out
    assert "evt1" in out


def test_format_calendar_name_list_marks_default():
    cals = [
        {"id": "c1", "name": "Calendar", "isDefaultCalendar": True},
        {"id": "c2", "name": "Birthdays", "isDefaultCalendar": False},
    ]
    out = fmt.format_calendar_name_list(cals)
    lines = out.splitlines()
    assert lines[0].startswith("*")
    assert lines[1].startswith(" ")
    assert "Calendar" in lines[0]
    assert "Birthdays" in lines[1]
