"""CalDAV calendar backend: iCalendar parse (list/get) and emit (create/update/respond).

All network I/O funnels through caldav_client.request, so these tests monkeypatch
that single choke point and feed real iCalendar bodies — no live calls.
"""

import icalendar
import pytest

from google_cli import calendar, caldav_client
from google_cli.config import Config


# A multistatus REPORT body with three events: a timed event in Europe/Rome, an
# all-day event, and a weekly-recurring standup. Mirrors Google's CalDAV output,
# including line folding (continuation lines begin with a space).
MULTISTATUS = """<?xml version="1.0" encoding="UTF-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
 <D:response>
  <D:href>/caldav/v2/me%40gmail.com/events/evt-timed%40google.com.ics</D:href>
  <D:propstat>
   <D:status>HTTP/1.1 200 OK</D:status>
   <D:prop>
    <D:getetag>"111"</D:getetag>
    <caldav:calendar-data>BEGIN:VCALENDAR
PRODID:-//Google Inc//Google Calendar 70.9054//EN
VERSION:2.0
BEGIN:VEVENT
DTSTART;TZID=Europe/Rome:20260714T100000
DTEND;TZID=Europe/Rome:20260714T110000
UID:evt-timed@google.com
SUMMARY:Lunch with a very long title that Google would fold across lines ok
 ay
LOCATION:Roma
DESCRIPTION:See https://example.com/x for details
ORGANIZER;CN=Me:mailto:me@gmail.com
ATTENDEE;CUTYPE=INDIVIDUAL;PARTSTAT=ACCEPTED;CN=Me:mailto:me@gmail.com
ATTENDEE;PARTSTAT=NEEDS-ACTION;CN=Bob:mailto:bob@example.com
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR
</caldav:calendar-data>
   </D:prop>
  </D:propstat>
 </D:response>
 <D:response>
  <D:href>/caldav/v2/me%40gmail.com/events/evt-allday.ics</D:href>
  <D:propstat>
   <D:status>HTTP/1.1 200 OK</D:status>
   <D:prop>
    <D:getetag>"222"</D:getetag>
    <caldav:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260715
DTEND;VALUE=DATE:20260716
UID:evt-allday
SUMMARY:Public holiday
END:VEVENT
END:VCALENDAR
</caldav:calendar-data>
   </D:prop>
  </D:propstat>
 </D:response>
 <D:response>
  <D:href>/caldav/v2/me%40gmail.com/events/evt-weekly.ics</D:href>
  <D:propstat>
   <D:status>HTTP/1.1 200 OK</D:status>
   <D:prop>
    <D:getetag>"333"</D:getetag>
    <caldav:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20260713T090000Z
DTEND:20260713T091500Z
UID:evt-weekly
SUMMARY:Standup
RRULE:FREQ=DAILY;COUNT=5
END:VEVENT
END:VCALENDAR
</caldav:calendar-data>
   </D:prop>
  </D:propstat>
 </D:response>
</D:multistatus>
"""


@pytest.fixture(autouse=True)
def _patch_email(monkeypatch):
    monkeypatch.setattr(caldav_client, "account_email", lambda config, **kw: "me@gmail.com")


def _capture_request(monkeypatch, response=(207, "")):
    calls = []

    def fake(config, method, url, *, body=None, depth=None, content_type=None, extra_headers=None):
        calls.append({"method": method, "url": url, "body": body, "extra_headers": extra_headers})
        if callable(response):
            return response(method, url, body)
        return response

    monkeypatch.setattr(caldav_client, "request", fake)
    return calls


# -- parse: list_events_between -----------------------------------------


def test_list_parses_timed_event_with_tzid(monkeypatch):
    _capture_request(monkeypatch, (207, MULTISTATUS))
    events = calendar.list_events(Config(), days_ahead=10, days_back=5)

    timed = next(e for e in events if e["id"] == "evt-timed@google.com")
    assert timed["summary"] == "Lunch with a very long title that Google would fold across lines okay"
    assert timed["start"]["timeZone"] == "Europe/Rome"
    assert timed["start"]["dateTime"].startswith("2026-07-14T10:00:00")
    assert timed["location"] == "Roma"
    emails = {a["email"]: a for a in timed["attendees"]}
    assert emails["me@gmail.com"]["responseStatus"] == "accepted"
    assert emails["bob@example.com"]["responseStatus"] == "needsAction"
    assert timed["organizer"]["email"] == "me@gmail.com"


def test_list_parses_all_day_event(monkeypatch):
    _capture_request(monkeypatch, (207, MULTISTATUS))
    events = calendar.list_events(Config(), days_ahead=10, days_back=5)
    allday = next(e for e in events if e["id"] == "evt-allday")
    assert allday["start"] == {"date": "2026-07-15"}
    assert "dateTime" not in allday["start"]


def test_list_expands_recurring_into_occurrences(monkeypatch):
    _capture_request(monkeypatch, (207, MULTISTATUS))
    events = calendar.list_events(Config(), days_ahead=10, days_back=5)
    standups = [e for e in events if e["id"] == "evt-weekly"]
    # DAILY;COUNT=5 from 2026-07-13 -> five concrete occurrences in-window.
    assert len(standups) == 5
    starts = sorted(e["start"]["dateTime"] for e in standups)
    assert starts[0].startswith("2026-07-13T09:00:00")
    assert starts[-1].startswith("2026-07-17T09:00:00")


def test_list_user_timezone_converts_times(monkeypatch):
    _capture_request(monkeypatch, (207, MULTISTATUS))
    events = calendar.list_events(Config(), days_ahead=10, days_back=5, user_timezone="America/New_York")
    timed = next(e for e in events if e["id"] == "evt-timed@google.com")
    # 10:00 Europe/Rome (UTC+2 in July) -> 04:00 America/New_York (UTC-4).
    assert timed["start"]["timeZone"] == "America/New_York"
    assert timed["start"]["dateTime"].startswith("2026-07-14T04:00:00")


def test_list_limit_truncates(monkeypatch):
    _capture_request(monkeypatch, (207, MULTISTATUS))
    events = calendar.list_events(Config(), days_ahead=10, days_back=5, limit=2)
    assert len(events) == 2


def test_list_no_details_omits_attendees(monkeypatch):
    _capture_request(monkeypatch, (207, MULTISTATUS))
    events = calendar.list_events(Config(), days_ahead=10, days_back=5, include_details=False)
    timed = next(e for e in events if e["id"] == "evt-timed@google.com")
    assert "attendees" not in timed
    assert timed["summary"]  # basic fields still present


# -- emit: create_event -------------------------------------------------


def _get_put_ics(calls):
    put = next(c for c in calls if c["method"] == "PUT")
    return icalendar.Calendar.from_ical(put["body"]), put


def test_create_emits_utc_ical_with_attendees_and_rrule(monkeypatch):
    calls = _capture_request(monkeypatch, (201, ""))
    result = calendar.create_event(
        Config(),
        subject="Sync",
        start="2026-07-20T15:00:00",
        end="2026-07-20T16:00:00",
        timezone="Europe/London",
        location="HQ",
        body="agenda",
        attendees=["bob@example.com"],
        recurrence="weekly",
        recurrence_end_date="2026-08-31",
    )
    assert result["status"] == "created"
    cal, put = _get_put_ics(calls)
    ev = cal.walk("VEVENT")[0]
    assert str(ev.get("SUMMARY")) == "Sync"
    # 15:00 London (BST, UTC+1) -> 14:00 UTC, emitted as a Z time (no VTIMEZONE).
    assert ev.get("DTSTART").to_ical().decode() == "20260720T140000Z"
    assert ev.get("DTEND").to_ical().decode() == "20260720T150000Z"
    assert str(ev.get("LOCATION")) == "HQ"
    attendees = ev.get("ATTENDEE")
    assert "mailto:bob@example.com" in str(attendees)
    assert "FREQ=WEEKLY" in ev.get("RRULE").to_ical().decode()
    # create must not clobber an existing event of the same id.
    assert put["extra_headers"] == {"If-None-Match": "*"}


def test_create_all_day_uses_exclusive_end(monkeypatch):
    calls = _capture_request(monkeypatch, (201, ""))
    calendar.create_event(Config(), subject="Holiday", start="2026-07-20", timezone="UTC", all_day=True)
    cal, _ = _get_put_ics(calls)
    ev = cal.walk("VEVENT")[0]
    assert ev.get("DTSTART").to_ical().decode() == "20260720"
    assert ev.get("DTEND").to_ical().decode() == "20260721"


def test_create_validates_timezone(monkeypatch):
    _capture_request(monkeypatch, (201, ""))
    with pytest.raises(ValueError, match="Invalid timezone"):
        calendar.create_event(Config(), subject="x", start="2026-07-20T10:00:00", timezone="Mars/Phobos")


# -- update / respond / delete ------------------------------------------

EXISTING_ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20260720T140000Z
DTEND:20260720T150000Z
UID:evt-timed@google.com
SUMMARY:Old title
SEQUENCE:2
ATTENDEE;PARTSTAT=NEEDS-ACTION:mailto:me@gmail.com
END:VEVENT
END:VCALENDAR
"""


def test_update_patches_and_bumps_sequence(monkeypatch):
    def responder(method, url, body):
        return (200, EXISTING_ICS) if method == "GET" else (204, "")

    calls = _capture_request(monkeypatch, responder)
    calendar.update_event(Config(), event_id="evt-timed@google.com", subject="New title")
    cal, _ = _get_put_ics(calls)
    ev = cal.walk("VEVENT")[0]
    assert str(ev.get("SUMMARY")) == "New title"
    assert int(ev.get("SEQUENCE")) == 3


def test_update_requires_timezone_for_time_change(monkeypatch):
    _capture_request(monkeypatch, (200, EXISTING_ICS))
    with pytest.raises(ValueError, match="timezone is required"):
        calendar.update_event(Config(), event_id="x", start="2026-07-20T10:00:00")


def test_respond_sets_partstat_for_self(monkeypatch):
    def responder(method, url, body):
        return (200, EXISTING_ICS) if method == "GET" else (204, "")

    calls = _capture_request(monkeypatch, responder)
    out = calendar.respond_event(Config(), event_id="evt-timed@google.com", response="accept")
    assert out["status"] == "accepted"
    cal, _ = _get_put_ics(calls)
    ev = cal.walk("VEVENT")[0]
    assert str(ev.get("ATTENDEE").params["PARTSTAT"]) == "ACCEPTED"


def test_delete_issues_delete(monkeypatch):
    calls = _capture_request(monkeypatch, (204, ""))
    out = calendar.delete_event(Config(), event_id="evt-timed@google.com")
    assert out["status"] == "deleted"
    assert any(c["method"] == "DELETE" for c in calls)


def test_get_event_parses_single_ics(monkeypatch):
    _capture_request(monkeypatch, (200, EXISTING_ICS))
    ev = calendar.get_event(Config(), event_id="evt-timed@google.com")
    assert ev["id"] == "evt-timed@google.com"
    assert ev["summary"] == "Old title"


# -- multistatus parsing corner: 404 half must not mask 200 prop --------


def test_parse_multistatus_ignores_404_propstat():
    xml = """<D:multistatus xmlns:D="DAV:" xmlns:caldav="urn:ietf:params:xml:ns:caldav">
     <D:response>
      <D:href>/x/events/</D:href>
      <D:propstat><D:status>HTTP/1.1 200 OK</D:status>
       <D:prop><D:displayname>Work</D:displayname>
        <D:resourcetype><D:collection/><caldav:calendar/></D:resourcetype></D:prop></D:propstat>
      <D:propstat><D:status>HTTP/1.1 404 Not Found</D:status>
       <D:prop><D:getetag/></D:prop></D:propstat>
     </D:response>
    </D:multistatus>"""
    records = caldav_client.parse_multistatus(xml)
    assert records[0]["displayname"] == "Work"
    assert "{urn:ietf:params:xml:ns:caldav}calendar" in records[0]["resourcetypes"]
