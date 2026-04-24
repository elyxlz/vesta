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


def test_format_email_list():
    assert fmt.format_email_list([]) == "(no messages)"
    emails = [
        {
            "id": "AAA",
            "subject": "Hello",
            "from": {"emailAddress": {"address": "a@x.com"}},
            "receivedDateTime": "2026-04-24T09:00:00Z",
            "isRead": False,
        },
        {
            "id": "BBB",
            "subject": "Read",
            "from": {"emailAddress": {"address": "b@x.com"}},
            "receivedDateTime": "2026-04-23T08:00:00Z",
            "isRead": True,
        },
    ]
    lines = fmt.format_email_list(emails).splitlines()
    assert "a@x.com" in lines[0] and "Hello" in lines[0] and " *" in lines[0] and "AAA" in lines[0]
    assert " *" not in lines[1] and "BBB" in lines[1]


def test_format_calendar_event_list():
    assert fmt.format_calendar_event_list([]) == "(no events)"
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
    assert all(s in out for s in ("2026-04-24T09:00:00", "2026-04-24T09:30:00", "Standup", "Zoom", "evt1"))


def test_format_calendar_name_list_marks_default():
    lines = fmt.format_calendar_name_list(
        [
            {"id": "c1", "name": "Calendar", "isDefaultCalendar": True},
            {"id": "c2", "name": "Birthdays", "isDefaultCalendar": False},
        ]
    ).splitlines()
    assert lines[0].startswith("*") and "Calendar" in lines[0]
    assert lines[1].startswith(" ") and "Birthdays" in lines[1]
