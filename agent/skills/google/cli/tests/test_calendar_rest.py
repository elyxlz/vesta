"""Calendar command routing + Google Calendar REST v3 request construction.

Replaces the real ``build("calendar", "v3")`` service with a fake resource chain
(recorded calls, canned responses) and drives the commands through
``cli._dispatch_calendar`` (the same dispatch the CLI uses) to assert the exact
methods, request kwargs, and JSON bodies the commands build. Hermetic: no
network, no token store.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httplib2
import pytest
from googleapiclient.errors import HttpError

from google_cli import calendar, cli
from google_cli.config import Config


# -- harness -------------------------------------------------------------


class _FakeService:
    """Mimics googleapiclient's calendar v3 resource chain; records every call.

    ``responses`` maps a method key ("events.list", "calendarList.list", ...) to
    a dict (always returned), a list of dicts (popped in order, for pagination),
    or an Exception (raised).
    """

    def __init__(self):
        self.calls = []
        self.responses = {}

    def events(self):
        return _FakeResource(self, "events")

    def calendarList(self):  # noqa: N802 (mirrors the googleapiclient API name)
        return _FakeResource(self, "calendarList")


class _FakeResource:
    def __init__(self, service, name):
        self._service = service
        self._name = name

    def __getattr__(self, method_name):
        def method(**kwargs):
            return _FakeRequest(self._service, f"{self._name}.{method_name}", kwargs)

        return method


class _FakeRequest:
    def __init__(self, service, method, kwargs):
        self._service = service
        self._method = method
        self._kwargs = kwargs

    def execute(self):
        self._service.calls.append({"method": self._method, "kwargs": self._kwargs})
        if self._method not in self._service.responses:
            return {}
        response = self._service.responses[self._method]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, list):
            return response.pop(0) if response else {}
        return response


@pytest.fixture
def svc(monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(calendar.api, "calendar_service", lambda config: service)
    return service


def _http_error(code, payload):
    return HttpError(httplib2.Response({"status": code}), json.dumps(payload).encode())


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


def test_list_events_method_and_params(svc):
    svc.responses = {"events.list": {"items": []}}
    result = cli._dispatch_calendar(_list_args(days_ahead=3, days_back=1), Config())
    call = svc.calls[0]
    assert call["method"] == "events.list"
    kwargs = call["kwargs"]
    assert kwargs["calendarId"] == "primary"
    assert kwargs["singleEvents"] is True
    assert kwargs["orderBy"] == "startTime"
    assert kwargs["maxResults"] == 250
    assert kwargs["timeMin"].endswith("Z") and kwargs["timeMax"].endswith("Z")
    assert result == []


def test_list_events_custom_calendar_id_is_passed_through(svc):
    cli._dispatch_calendar(_list_args(calendar="team@group.calendar.google.com"), Config())
    assert svc.calls[0]["kwargs"]["calendarId"] == "team@group.calendar.google.com"


def test_list_events_shapes_and_limits(svc):
    items = [
        {"id": f"e{i}", "summary": f"Event {i}", "start": {"dateTime": "2026-07-20T10:00:00Z"}, "end": {}, "attendees": [{"email": "a@x.com"}]}
        for i in range(3)
    ]
    svc.responses = {"events.list": {"items": items}}
    result = cli._dispatch_calendar(_list_args(limit=2), Config())
    assert svc.calls[0]["kwargs"]["maxResults"] == 2
    assert [e["id"] for e in result] == ["e0", "e1"]
    assert result[0]["attendees"] == [{"email": "a@x.com"}]


def test_list_events_no_details_is_compact(svc):
    svc.responses = {"events.list": {"items": [{"id": "e1", "summary": "S", "description": "long", "attendees": [{"email": "a@x.com"}]}]}}
    result = cli._dispatch_calendar(_list_args(no_details=True), Config())
    assert "description" not in result[0]
    assert "attendees" not in result[0]


def test_list_events_user_timezone_is_passed_to_the_api(svc):
    svc.responses = {"events.list": {"items": []}}
    cli._dispatch_calendar(_list_args(user_timezone="Europe/London"), Config())
    assert svc.calls[0]["kwargs"]["timeZone"] == "Europe/London"


def test_list_events_rejects_invalid_user_timezone_before_any_request(svc):
    with pytest.raises(ValueError, match="Invalid timezone"):
        cli._dispatch_calendar(_list_args(user_timezone="Mars/Olympus"), Config())
    assert svc.calls == []


def test_list_events_follows_pagination(svc):
    svc.responses = {
        "events.list": [
            {"items": [{"id": "e1"}], "nextPageToken": "tok2"},
            {"items": [{"id": "e2"}]},
        ]
    }
    result = calendar.list_events_between(Config(), start=datetime(2026, 7, 20, tzinfo=UTC), end=datetime(2026, 7, 27, tzinfo=UTC))
    assert [e["id"] for e in result] == ["e1", "e2"]
    assert "pageToken" not in svc.calls[0]["kwargs"]
    assert svc.calls[1]["kwargs"]["pageToken"] == "tok2"


def test_list_events_limit_stops_pagination(svc):
    svc.responses = {"events.list": [{"items": [{"id": "e1"}, {"id": "e2"}, {"id": "e3"}], "nextPageToken": "tok2"}]}
    result = calendar.list_events_between(Config(), start=datetime(2026, 7, 20, tzinfo=UTC), end=datetime(2026, 7, 27, tzinfo=UTC), limit=2)
    assert [e["id"] for e in result] == ["e1", "e2"]
    assert len(svc.calls) == 1


def test_list_calendars_method(svc):
    svc.responses = {"calendarList.list": {"items": [{"id": "primary", "summary": "Me", "primary": True, "accessRole": "owner"}]}}
    result = cli._dispatch_calendar(SimpleNamespace(command="calendars"), Config())
    assert svc.calls[0]["method"] == "calendarList.list"
    assert result == [{"id": "primary", "summary": "Me", "primary": True, "accessRole": "owner"}]


def test_get_event_method_and_shape_matches_list(svc):
    svc.responses = {"events.get": {"id": "evt@123", "summary": "S", "htmlLink": "https://calendar.google.com/x"}}
    result = cli._dispatch_calendar(SimpleNamespace(command="get", calendar="primary", event_id="evt@123"), Config())
    assert svc.calls[0]["method"] == "events.get"
    assert svc.calls[0]["kwargs"] == {"calendarId": "primary", "eventId": "evt@123"}
    # get shapes through the same _event_to_dict as list: normalized keys, no raw extras.
    assert result["id"] == "evt@123"
    assert result["attendees"] == []
    assert "htmlLink" not in result


# -- create ---------------------------------------------------------------


def test_create_event_body_and_send_updates(svc):
    svc.responses = {"events.insert": {"id": "new1"}}
    result = cli._dispatch_calendar(
        _create_args(end="2026-07-20T16:00:00", location="Room 1", body="notes", attendees=["a@x.com", "b@y.com"]),
        Config(),
    )
    call = svc.calls[0]
    assert call["method"] == "events.insert"
    assert call["kwargs"]["calendarId"] == "primary"
    assert call["kwargs"]["sendUpdates"] == "all"
    body = call["kwargs"]["body"]
    assert body["summary"] == "Sync"
    assert body["start"] == {"dateTime": "2026-07-20T15:00:00", "timeZone": "Europe/London"}
    assert body["end"] == {"dateTime": "2026-07-20T16:00:00", "timeZone": "Europe/London"}
    assert body["location"] == "Room 1"
    assert body["description"] == "notes"
    assert body["attendees"] == [{"email": "a@x.com"}, {"email": "b@y.com"}]
    assert result == {"status": "created", "id": "new1", "calendar": "primary"}


def test_create_event_defaults_end_to_plus_one_hour(svc):
    cli._dispatch_calendar(_create_args(start="2026-07-20T09:00:00"), Config())
    assert svc.calls[0]["kwargs"]["body"]["end"] == {"dateTime": "2026-07-20T10:00:00", "timeZone": "Europe/London"}


def test_create_all_day_event_uses_exclusive_end_date(svc):
    cli._dispatch_calendar(_create_args(start="2026-12-25", all_day=True), Config())
    body = svc.calls[0]["kwargs"]["body"]
    assert body["start"] == {"date": "2026-12-25"}
    assert body["end"] == {"date": "2026-12-26"}


def test_create_date_only_start_implies_all_day(svc):
    # No --all-day flag, but a date-only start: a mixed date/dateTime pair would 400.
    cli._dispatch_calendar(_create_args(start="2026-12-25"), Config())
    body = svc.calls[0]["kwargs"]["body"]
    assert body["start"] == {"date": "2026-12-25"}
    assert body["end"] == {"date": "2026-12-26"}


def test_create_recurring_event_builds_rrule_with_until(svc):
    cli._dispatch_calendar(_create_args(recurrence="weekly", recurrence_end_date="2026-12-31"), Config())
    assert svc.calls[0]["kwargs"]["body"]["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261231T235959Z"]


def test_create_all_day_recurring_until_is_a_date(svc):
    # RFC 5545: UNTIL's value type must match DTSTART's; DATE for all-day events.
    cli._dispatch_calendar(_create_args(start="2026-12-25", all_day=True, recurrence="yearly", recurrence_end_date="2028-12-31"), Config())
    assert svc.calls[0]["kwargs"]["body"]["recurrence"] == ["RRULE:FREQ=YEARLY;UNTIL=20281231"]


def test_create_rejects_invalid_timezone(svc):
    with pytest.raises(ValueError, match="Invalid timezone"):
        cli._dispatch_calendar(_create_args(timezone="Mars/Olympus"), Config())
    assert svc.calls == []


# -- update / delete ------------------------------------------------------


def test_update_event_patch_and_send_updates(svc):
    cli._dispatch_calendar(_update_args(subject="Renamed"), Config())
    assert svc.calls[0]["method"] == "events.get"  # series resolution fetch
    call = svc.calls[1]
    assert call["method"] == "events.patch"
    assert call["kwargs"]["eventId"] == "evt1"
    assert call["kwargs"]["sendUpdates"] == "all"
    assert call["kwargs"]["body"] == {"summary": "Renamed"}


def test_update_start_requires_timezone(svc):
    with pytest.raises(ValueError, match="timezone"):
        cli._dispatch_calendar(_update_args(start="2026-07-20T10:00:00"), Config())
    assert svc.calls == []


def test_update_with_no_fields_errors(svc):
    with pytest.raises(ValueError, match="at least one field"):
        cli._dispatch_calendar(_update_args(), Config())
    assert svc.calls == []


def test_update_occurrence_id_resolves_to_series_master(svc):
    svc.responses = {"events.get": {"id": "evt1_20260720", "recurringEventId": "evt1"}}
    result = cli._dispatch_calendar(_update_args(event_id="evt1_20260720", subject="Renamed"), Config())
    patch = svc.calls[1]
    assert patch["method"] == "events.patch"
    assert patch["kwargs"]["eventId"] == "evt1"
    assert result["id"] == "evt1"


def test_update_single_sided_type_mismatch_is_rejected(svc):
    # Existing event is timed; patching start alone to an all-day date would 400 at the API.
    svc.responses = {"events.get": {"id": "evt1", "start": {"dateTime": "2026-07-20T10:00:00Z"}, "end": {"dateTime": "2026-07-20T11:00:00Z"}}}
    with pytest.raises(ValueError, match="both"):
        cli._dispatch_calendar(_update_args(start="2026-07-21", timezone="Europe/London"), Config())
    assert len(svc.calls) == 1  # the fetch only, no PATCH


def test_update_single_sided_matching_type_passes(svc):
    svc.responses = {"events.get": {"id": "evt1", "start": {"dateTime": "2026-07-20T10:00:00Z"}, "end": {"dateTime": "2026-07-20T11:00:00Z"}}}
    cli._dispatch_calendar(_update_args(start="2026-07-20T12:00:00", timezone="Europe/London"), Config())
    assert svc.calls[1]["kwargs"]["body"] == {"start": {"dateTime": "2026-07-20T12:00:00", "timeZone": "Europe/London", "date": None}}


def test_update_flipping_to_all_day_nulls_the_datetime_subfields(svc):
    # Patch semantics keep omitted subfields, so flipping timed -> all-day must null dateTime/timeZone.
    svc.responses = {"events.get": {"id": "evt1", "start": {"dateTime": "2026-07-20T10:00:00Z"}, "end": {"dateTime": "2026-07-20T11:00:00Z"}}}
    cli._dispatch_calendar(_update_args(start="2026-07-22", end="2026-07-23", timezone="Europe/London"), Config())
    body = svc.calls[1]["kwargs"]["body"]
    assert body["start"] == {"date": "2026-07-22", "dateTime": None, "timeZone": None}
    assert body["end"] == {"date": "2026-07-23", "dateTime": None, "timeZone": None}


def test_update_flipping_to_timed_nulls_the_date_subfield(svc):
    svc.responses = {"events.get": {"id": "evt1", "start": {"date": "2026-07-20"}, "end": {"date": "2026-07-21"}}}
    cli._dispatch_calendar(_update_args(start="2026-07-22T10:00:00", end="2026-07-22T11:00:00", timezone="Europe/London"), Config())
    body = svc.calls[1]["kwargs"]["body"]
    assert body["start"] == {"dateTime": "2026-07-22T10:00:00", "timeZone": "Europe/London", "date": None}
    assert body["end"] == {"dateTime": "2026-07-22T11:00:00", "timeZone": "Europe/London", "date": None}


def test_delete_event_notifies_attendees_by_default(svc):
    result = cli._dispatch_calendar(SimpleNamespace(command="delete", calendar="primary", event_id="evt9", no_notification=False), Config())
    assert svc.calls[0]["method"] == "events.get"  # series resolution fetch
    call = svc.calls[1]
    assert call["method"] == "events.delete"
    assert call["kwargs"] == {"calendarId": "primary", "eventId": "evt9", "sendUpdates": "all"}
    assert result == {"status": "deleted", "event_id": "evt9"}


def test_delete_event_no_notification_sets_send_updates_none(svc):
    cli._dispatch_calendar(SimpleNamespace(command="delete", calendar="primary", event_id="evt9", no_notification=True), Config())
    assert svc.calls[1]["kwargs"]["sendUpdates"] == "none"


def test_delete_occurrence_id_resolves_to_series_master(svc):
    svc.responses = {"events.get": {"id": "evt9_20260720", "recurringEventId": "evt9"}}
    result = cli._dispatch_calendar(
        SimpleNamespace(command="delete", calendar="primary", event_id="evt9_20260720", no_notification=False), Config()
    )
    assert svc.calls[1]["method"] == "events.delete"
    assert svc.calls[1]["kwargs"]["eventId"] == "evt9"
    assert result == {"status": "deleted", "event_id": "evt9"}


# -- respond ---------------------------------------------------------------


def _respond_args(**over):
    base = dict(command="respond", calendar="primary", event_id="evt5", response="accept", message=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_respond_sets_self_attendee_status_without_guest_fanout(svc):
    svc.responses = {
        "events.get": {
            "id": "evt5",
            "attendees": [
                {"email": "other@x.com", "responseStatus": "needsAction"},
                {"email": "me@gmail.com", "self": True, "responseStatus": "needsAction"},
            ],
        }
    }
    result = cli._dispatch_calendar(_respond_args(message="see you there"), Config())
    assert svc.calls[0]["method"] == "events.get"
    patch = svc.calls[1]
    assert patch["method"] == "events.patch"
    # An RSVP must not email the guest list.
    assert patch["kwargs"]["sendUpdates"] == "none"
    me = [a for a in patch["kwargs"]["body"]["attendees"] if "self" in a][0]
    assert me["responseStatus"] == "accepted"
    assert me["comment"] == "see you there"
    assert result == {"status": "accepted", "event_id": "evt5"}


def test_respond_without_self_attendee_errors(svc):
    svc.responses = {"events.get": {"id": "evt5", "attendees": [{"email": "other@x.com"}]}}
    with pytest.raises(ValueError, match="not an attendee"):
        cli._dispatch_calendar(_respond_args(), Config())
    assert len(svc.calls) == 1  # no PATCH after the failed match


def test_respond_without_attendees_errors(svc):
    svc.responses = {"events.get": {"id": "evt5"}}
    with pytest.raises(ValueError, match="no attendees"):
        cli._dispatch_calendar(_respond_args(), Config())


# -- API error surfacing ---------------------------------------------------


def test_http_401_points_at_reauth(svc):
    svc.responses = {"calendarList.list": _http_error(401, {"error": {"message": "Invalid Credentials"}})}
    with pytest.raises(calendar.CalendarAuthError, match="google auth login"):
        calendar.list_calendars(Config())


def test_http_access_not_configured_points_at_byo_reauth(svc):
    svc.responses = {"calendarList.list": _http_error(403, {"error": {"status": "PERMISSION_DENIED", "message": "accessNotConfigured"}})}
    with pytest.raises(calendar.CalendarAuthError) as ei:
        calendar.list_calendars(Config())
    message = str(ei.value)
    assert "shared Thunderbird client" in message
    assert "credentials.json" in message
    assert "google auth login" in message


def test_http_rate_limit_403_is_not_an_auth_error(svc):
    svc.responses = {
        "calendarList.list": _http_error(403, {"error": {"errors": [{"reason": "rateLimitExceeded"}], "message": "Rate Limit Exceeded"}})
    }
    with pytest.raises(RuntimeError) as ei:
        calendar.list_calendars(Config())
    assert not isinstance(ei.value, calendar.CalendarAuthError)
    message = str(ei.value)
    assert "retry later" in message
    assert "auth login" not in message


# -- list window construction (pure) ----------------------------------------


def test_rfc3339_naive_datetimes_are_treated_as_utc():
    assert calendar._rfc3339(datetime(2026, 7, 20, 10, 0)) == "2026-07-20T10:00:00Z"
    assert calendar._rfc3339(datetime(2026, 7, 20, 10, 0, tzinfo=UTC)) == "2026-07-20T10:00:00Z"


def test_list_events_between_used_by_monitor_passes_window(svc):
    svc.responses = {"events.list": {"items": []}}
    start = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
    end = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
    calendar.list_events_between(Config(), calendar_id="primary", start=start, end=end, include_details=False, limit=50)
    kwargs = svc.calls[0]["kwargs"]
    assert kwargs["timeMin"] == "2026-07-20T10:00:00Z"
    assert kwargs["timeMax"] == "2026-07-21T10:00:00Z"
    assert kwargs["maxResults"] == 50
