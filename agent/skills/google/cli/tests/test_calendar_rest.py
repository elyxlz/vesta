"""Calendar command routing + Google Calendar REST v3 request construction.

Mocks the single HTTP choke point (``calendar._http``) and drives the commands
through ``cli._dispatch_calendar`` (the same dispatch the CLI uses) to assert
the exact endpoints, query params, and JSON bodies the commands build. Hermetic:
no network, no token store.
"""

import io
import json
import urllib.error
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from google_cli import calendar, cli
from google_cli.config import Config


# -- harness -------------------------------------------------------------


class _Recorder:
    """Capture calendar._http calls and feed canned responses."""

    def __init__(self, responses=None):
        self.calls = []
        self.responses = responses or {}

    def __call__(self, config, method, path, *, params=None, body=None):
        self.calls.append({"method": method, "path": path, "params": params, "body": body})
        # Match a canned response by (method, substring) if provided.
        for (m, needle), resp in self.responses.items():
            if m == method and needle in path:
                return resp
        return {}


@pytest.fixture
def rec(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(calendar, "_http", recorder)
    return recorder


def _list_args(**over):
    base = dict(command="list", calendar="primary", days_ahead=7, days_back=0, limit=None, no_details=False, user_timezone=None)
    base.update(over)
    return SimpleNamespace(**base)


def _create_args(**over):
    base = dict(
        command="create",
        calendar="primary",
        subject="Sync",
        start="2026-07-20T15:00:00",
        end=None,
        location=None,
        body=None,
        attendees=None,
        timezone="Europe/London",
        all_day=False,
        recurrence=None,
        recurrence_end_date=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _update_args(**over):
    base = dict(
        command="update", calendar="primary", event_id="evt1", subject=None, start=None, end=None, location=None, body=None, timezone=None
    )
    base.update(over)
    return SimpleNamespace(**base)


# -- list / calendars / get ----------------------------------------------


def test_list_events_endpoint_and_params(rec):
    rec.responses = {("GET", "/events"): {"items": []}}
    result = cli._dispatch_calendar(_list_args(days_ahead=3, days_back=1), Config())
    call = rec.calls[0]
    assert call["method"] == "GET"
    assert call["path"] == "/calendars/primary/events"
    assert call["params"]["singleEvents"] == "true"
    assert call["params"]["orderBy"] == "startTime"
    assert call["params"]["maxResults"] == 250
    assert call["params"]["timeMin"].endswith("Z") and call["params"]["timeMax"].endswith("Z")
    assert result == []


def test_list_events_custom_calendar_is_url_encoded(rec):
    cli._dispatch_calendar(_list_args(calendar="team@group.calendar.google.com"), Config())
    assert rec.calls[0]["path"] == "/calendars/team%40group.calendar.google.com/events"


def test_list_events_shapes_and_limits(rec):
    items = [
        {"id": f"e{i}", "summary": f"Event {i}", "start": {"dateTime": "2026-07-20T10:00:00Z"}, "end": {}, "attendees": [{"email": "a@x.com"}]}
        for i in range(3)
    ]
    rec.responses = {("GET", "/events"): {"items": items}}
    result = cli._dispatch_calendar(_list_args(limit=2), Config())
    assert rec.calls[0]["params"]["maxResults"] == 2
    assert [e["id"] for e in result] == ["e0", "e1"]
    assert result[0]["attendees"] == [{"email": "a@x.com"}]


def test_list_events_no_details_is_compact(rec):
    rec.responses = {("GET", "/events"): {"items": [{"id": "e1", "summary": "S", "description": "long", "attendees": [{"email": "a@x.com"}]}]}}
    result = cli._dispatch_calendar(_list_args(no_details=True), Config())
    assert "description" not in result[0]
    assert "attendees" not in result[0]


def test_list_events_user_timezone_is_passed_to_the_api(rec):
    rec.responses = {("GET", "/events"): {"items": []}}
    cli._dispatch_calendar(_list_args(user_timezone="Europe/London"), Config())
    assert rec.calls[0]["params"]["timeZone"] == "Europe/London"


def test_list_calendars_endpoint(rec):
    rec.responses = {("GET", "calendarList"): {"items": [{"id": "primary", "summary": "Me", "primary": True, "accessRole": "owner"}]}}
    result = cli._dispatch_calendar(SimpleNamespace(command="calendars"), Config())
    assert rec.calls[0]["method"] == "GET"
    assert rec.calls[0]["path"] == "/users/me/calendarList"
    assert result == [{"id": "primary", "summary": "Me", "primary": True, "accessRole": "owner"}]


def test_get_event_endpoint(rec):
    rec.responses = {("GET", "/events/evt%40123"): {"id": "evt@123"}}
    result = cli._dispatch_calendar(SimpleNamespace(command="get", calendar="primary", event_id="evt@123"), Config())
    assert rec.calls[0]["path"] == "/calendars/primary/events/evt%40123"
    assert result["id"] == "evt@123"


# -- create ---------------------------------------------------------------


def test_create_event_body_and_send_updates(rec):
    rec.responses = {("POST", "/events"): {"id": "new1"}}
    result = cli._dispatch_calendar(
        _create_args(end="2026-07-20T16:00:00", location="Room 1", body="notes", attendees=["a@x.com", "b@y.com"]),
        Config(),
    )
    call = rec.calls[0]
    assert call["method"] == "POST"
    assert call["path"] == "/calendars/primary/events"
    assert call["params"] == {"sendUpdates": "all"}
    body = call["body"]
    assert body["summary"] == "Sync"
    assert body["start"] == {"dateTime": "2026-07-20T15:00:00", "timeZone": "Europe/London"}
    assert body["end"] == {"dateTime": "2026-07-20T16:00:00", "timeZone": "Europe/London"}
    assert body["location"] == "Room 1"
    assert body["description"] == "notes"
    assert body["attendees"] == [{"email": "a@x.com"}, {"email": "b@y.com"}]
    assert result == {"status": "created", "id": "new1", "calendar": "primary"}


def test_create_event_defaults_end_to_plus_one_hour(rec):
    cli._dispatch_calendar(_create_args(start="2026-07-20T09:00:00"), Config())
    assert rec.calls[0]["body"]["end"] == {"dateTime": "2026-07-20T10:00:00", "timeZone": "Europe/London"}


def test_create_all_day_event_uses_exclusive_end_date(rec):
    cli._dispatch_calendar(_create_args(start="2026-12-25", all_day=True), Config())
    body = rec.calls[0]["body"]
    assert body["start"] == {"date": "2026-12-25"}
    assert body["end"] == {"date": "2026-12-26"}


def test_create_recurring_event_builds_rrule_with_until(rec):
    cli._dispatch_calendar(_create_args(recurrence="weekly", recurrence_end_date="2026-12-31"), Config())
    assert rec.calls[0]["body"]["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261231T235959Z"]


def test_create_rejects_invalid_timezone(rec):
    with pytest.raises(ValueError, match="Invalid timezone"):
        cli._dispatch_calendar(_create_args(timezone="Mars/Olympus"), Config())
    assert rec.calls == []


# -- update / delete ------------------------------------------------------


def test_update_event_patch_and_send_updates(rec):
    cli._dispatch_calendar(_update_args(subject="Renamed"), Config())
    call = rec.calls[0]
    assert call["method"] == "PATCH"
    assert call["path"] == "/calendars/primary/events/evt1"
    assert call["params"] == {"sendUpdates": "all"}
    assert call["body"] == {"summary": "Renamed"}


def test_update_start_requires_timezone(rec):
    with pytest.raises(ValueError, match="timezone"):
        cli._dispatch_calendar(_update_args(start="2026-07-20T10:00:00"), Config())
    assert rec.calls == []


def test_update_with_no_fields_errors(rec):
    with pytest.raises(ValueError, match="at least one field"):
        cli._dispatch_calendar(_update_args(), Config())
    assert rec.calls == []


def test_delete_event_notifies_attendees_by_default(rec):
    result = cli._dispatch_calendar(SimpleNamespace(command="delete", calendar="primary", event_id="evt9", no_notification=False), Config())
    call = rec.calls[0]
    assert call["method"] == "DELETE"
    assert call["path"] == "/calendars/primary/events/evt9"
    assert call["params"] == {"sendUpdates": "all"}
    assert result == {"status": "deleted", "event_id": "evt9"}


def test_delete_event_no_notification_sets_send_updates_none(rec):
    cli._dispatch_calendar(SimpleNamespace(command="delete", calendar="primary", event_id="evt9", no_notification=True), Config())
    assert rec.calls[0]["params"] == {"sendUpdates": "none"}


# -- respond ---------------------------------------------------------------


def _respond_args(**over):
    base = dict(command="respond", calendar="primary", event_id="evt5", response="accept", message=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_respond_sets_self_attendee_status(rec):
    rec.responses = {
        ("GET", "/events/evt5"): {
            "id": "evt5",
            "attendees": [
                {"email": "other@x.com", "responseStatus": "needsAction"},
                {"email": "me@gmail.com", "self": True, "responseStatus": "needsAction"},
            ],
        }
    }
    result = cli._dispatch_calendar(_respond_args(message="see you there"), Config())
    assert rec.calls[0]["method"] == "GET"
    patch = rec.calls[1]
    assert patch["method"] == "PATCH"
    assert patch["params"] == {"sendUpdates": "all"}
    me = [a for a in patch["body"]["attendees"] if "self" in a][0]
    assert me["responseStatus"] == "accepted"
    assert me["comment"] == "see you there"
    assert result == {"status": "accepted", "event_id": "evt5"}


def test_respond_without_self_attendee_errors(rec):
    rec.responses = {("GET", "/events/evt5"): {"id": "evt5", "attendees": [{"email": "other@x.com"}]}}
    with pytest.raises(ValueError, match="not an attendee"):
        cli._dispatch_calendar(_respond_args(), Config())
    assert len(rec.calls) == 1  # no PATCH after the failed match


def test_respond_without_attendees_errors(rec):
    rec.responses = {("GET", "/events/evt5"): {"id": "evt5"}}
    with pytest.raises(ValueError, match="no attendees"):
        cli._dispatch_calendar(_respond_args(), Config())


# -- HTTP error surfacing ---------------------------------------------------


def _patch_urlopen_error(monkeypatch, code, payload):
    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(json.dumps(payload).encode()))

    monkeypatch.setattr(calendar.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(calendar, "_bearer", lambda config: "TOKEN")


def test_http_401_points_at_reauth(monkeypatch):
    _patch_urlopen_error(monkeypatch, 401, {"error": {"message": "Invalid Credentials"}})
    with pytest.raises(RuntimeError, match="google auth login"):
        calendar.list_calendars(Config())


def test_http_access_not_configured_points_at_enabling_the_api(monkeypatch):
    _patch_urlopen_error(monkeypatch, 403, {"error": {"status": "PERMISSION_DENIED", "message": "accessNotConfigured"}})
    with pytest.raises(RuntimeError, match="not enabled on your Google Cloud project"):
        calendar.list_calendars(Config())


# -- list window construction (pure) ----------------------------------------


def test_rfc3339_naive_datetimes_are_treated_as_utc():
    assert calendar._rfc3339(datetime(2026, 7, 20, 10, 0)) == "2026-07-20T10:00:00Z"
    assert calendar._rfc3339(datetime(2026, 7, 20, 10, 0, tzinfo=UTC)) == "2026-07-20T10:00:00Z"


def test_list_events_between_used_by_monitor_passes_window(rec):
    rec.responses = {("GET", "/events"): {"items": []}}
    start = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    end = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
    calendar.list_events_between(Config(), calendar_id="primary", start=start, end=end, include_details=False, limit=50)
    call = rec.calls[0]
    assert call["params"]["timeMin"] == "2026-07-20T10:00:00Z"
    assert call["params"]["timeMax"] == "2026-07-21T10:00:00Z"
    assert call["params"]["maxResults"] == 50
