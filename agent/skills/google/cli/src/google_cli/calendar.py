#!/usr/bin/env python3
"""Google Calendar on CalDAV.

The Calendar REST API (``calendar/v3``) is unusable under this skill's reused
Thunderbird OAuth client — its Cloud project has the Calendar API disabled, so
every REST call 403s with ``accessNotConfigured``. This module reimplements the
whole calendar command surface (list / calendars / get / create / update /
delete / respond) on **CalDAV** against
``https://apidata.googleusercontent.com/caldav/v2/{email}/`` using the OAuth
Bearer token from this skill's token store — the same path Thunderbird uses.

The HTTP/DAV plumbing lives in :mod:`caldav_client`; here we build CalDAV
REPORT/PUT bodies, parse and emit iCalendar via the ``icalendar`` library, and
expand recurring events into concrete occurrences with ``recurring_ical_events``
(mirroring REST's ``singleEvents=True``). Event dicts are shaped to match the old
REST output (``start``/``end`` objects, ``attendees``, ``organizer``,
``recurrence``) so existing callers — the CLI and the daemon monitor — keep
working unchanged: only the backend moved.

NOTE ON INVITES: creating/updating/deleting an event with attendees causes Google
to email calendar invites/updates to them — a real outward send. The
EMAIL_DRAFT_ONLY guard covers email sending only and does NOT block calendar
writes; use judgment before writing events with attendees.
"""

from __future__ import annotations

import re
import urllib.parse
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import icalendar
import recurring_ical_events

from . import caldav_client
from .config import Config

RECURRENCE_MAP = {
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
    "yearly": "YEARLY",
}

RESPONSE_TO_PARTSTAT = {
    "accept": "ACCEPTED",
    "decline": "DECLINED",
    "tentative": "TENTATIVE",
}

PARTSTAT_TO_RESPONSE = {
    "ACCEPTED": "accepted",
    "DECLINED": "declined",
    "TENTATIVE": "tentative",
    "NEEDS-ACTION": "needsAction",
    "DELEGATED": "delegated",
}

CALDAV_CALENDAR_TAG = "{urn:ietf:params:xml:ns:caldav}calendar"


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        raise ValueError(f"Invalid timezone: '{timezone}'. Use IANA names like 'Europe/London' or 'America/New_York'.")


# -- iCalendar -> normalized dict ---------------------------------------


def _prop_str(vevent, name: str) -> str:
    value = vevent.get(name)
    return str(value) if value is not None else ""


def _time_dict(prop, user_timezone: str | None) -> dict[str, Any]:
    """Convert an iCal DTSTART/DTEND property to a REST-style start/end object.

    Timed values become ``{"dateTime": <iso-with-offset>, "timeZone": <tzid>}``;
    all-day values become ``{"date": "YYYY-MM-DD"}``. A ``user_timezone`` converts
    timed values into that zone.
    """
    if prop is None:
        return {}
    value = prop.dt
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        tzid = prop.params.get("TZID") if hasattr(prop, "params") else None
        if user_timezone:
            value = value.astimezone(ZoneInfo(user_timezone))
            tzid = user_timezone
        elif tzid is None:
            tzid = getattr(value.tzinfo, "key", None) or str(value.tzinfo)
        return {"dateTime": value.isoformat(), "timeZone": tzid}
    if isinstance(value, date):
        return {"date": value.isoformat()}
    return {}


def _clean_addr(value) -> str:
    return re.sub(r"^mailto:", "", str(value), flags=re.IGNORECASE)


def _attendees(vevent) -> list[dict[str, Any]]:
    raw = vevent.get("ATTENDEE")
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for a in items:
        params = getattr(a, "params", {}) or {}
        partstat = str(params.get("PARTSTAT", "")).upper()
        out.append(
            {
                "email": _clean_addr(a),
                "displayName": str(params["CN"]) if "CN" in params else None,
                "responseStatus": PARTSTAT_TO_RESPONSE.get(partstat, partstat.lower() or None),
                "optional": str(params.get("ROLE", "")).upper() == "OPT-PARTICIPANT" or None,
            }
        )
    return out


def _organizer(vevent) -> dict[str, Any] | None:
    raw = vevent.get("ORGANIZER")
    if raw is None:
        return None
    params = getattr(raw, "params", {}) or {}
    return {"email": _clean_addr(raw), "displayName": str(params["CN"]) if "CN" in params else None}


def _recurrence(vevent) -> list[str]:
    out: list[str] = []
    for key in ("RRULE", "EXRULE", "RDATE", "EXDATE"):
        value = vevent.get(key)
        if value is None:
            continue
        items = value if isinstance(value, list) else [value]
        for item in items:
            out.append(f"{key}:" + item.to_ical().decode("utf-8"))
    return out


def _event_to_dict(vevent, *, href=None, etag=None, include_details=True, user_timezone=None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": _prop_str(vevent, "UID"),
        "summary": _prop_str(vevent, "SUMMARY"),
        "start": _time_dict(vevent.get("DTSTART"), user_timezone),
        "end": _time_dict(vevent.get("DTEND"), user_timezone),
        "location": _prop_str(vevent, "LOCATION") or None,
        "status": (_prop_str(vevent, "STATUS") or "").lower() or None,
    }
    if href:
        result["ics_href"] = href
    if etag:
        result["etag"] = etag
    if include_details:
        result["description"] = _prop_str(vevent, "DESCRIPTION") or None
        result["organizer"] = _organizer(vevent)
        result["attendees"] = _attendees(vevent)
        recurrence = _recurrence(vevent)
        if recurrence:
            result["recurrence"] = recurrence
    return result


def _sort_key(event: dict[str, Any]):
    start = event.get("start", {})
    value = start.get("dateTime") or start.get("date")
    if not value:
        return (1, datetime.max.replace(tzinfo=UTC))
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (0, parsed.astimezone(UTC))
    except ValueError:
        return (1, datetime.max.replace(tzinfo=UTC))


# -- CalDAV query -------------------------------------------------------


def _caldav_stamp(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _calendar_query_xml(start: datetime, end: datetime) -> str:
    return (
        '<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        "<d:prop><d:getetag/><c:calendar-data/></d:prop>"
        '<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">'
        f'<c:time-range start="{_caldav_stamp(start)}" end="{_caldav_stamp(end)}"/>'
        "</c:comp-filter></c:comp-filter></c:filter>"
        "</c:calendar-query>"
    )


def _expand(cal, start: datetime, end: datetime):
    """Expand a parsed VCALENDAR into concrete VEVENT occurrences in [start, end).

    Mirrors REST ``singleEvents=True``. Falls back to the raw VEVENTs if the
    recurrence expander chokes on an odd event, so one bad event never blanks the
    whole list.
    """
    try:
        return list(recurring_ical_events.of(cal).between(start, end))
    except Exception:
        return list(cal.walk("VEVENT"))


def list_events_between(
    config: Config,
    *,
    calendar_id: str = "primary",
    start: datetime,
    end: datetime,
    include_details: bool = True,
    user_timezone: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return normalized events overlapping ``[start, end)`` for a calendar."""
    url = caldav_client.collection_url(config, calendar_id)
    body = _calendar_query_xml(start, end)
    _status, text = caldav_client.request(config, "REPORT", url, body=body, depth="1")
    records = caldav_client.parse_multistatus(text)

    events: list[dict[str, Any]] = []
    for rec in records:
        cdata = rec.get("calendar_data")
        if not cdata:
            continue
        try:
            cal = icalendar.Calendar.from_ical(cdata)
        except Exception:
            continue
        for vevent in _expand(cal, start, end):
            events.append(
                _event_to_dict(
                    vevent,
                    href=rec.get("href"),
                    etag=rec.get("etag"),
                    include_details=include_details,
                    user_timezone=user_timezone,
                )
            )

    events.sort(key=_sort_key)
    if limit is not None:
        events = events[:limit]
    return events


def list_events(
    config: Config,
    *,
    calendar_id: str = "primary",
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
    user_timezone: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    tz = ZoneInfo(user_timezone) if user_timezone else UTC
    now_local = datetime.now(tz)
    start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_of_today - timedelta(days=days_back)
    end = start_of_today + timedelta(days=days_ahead + 1)
    return list_events_between(
        config,
        calendar_id=calendar_id,
        start=start,
        end=end,
        include_details=include_details,
        user_timezone=user_timezone,
        limit=limit,
    )


def _calendar_id_from_href(href: str) -> str:
    m = re.search(r"/caldav/v2/([^/]+)/", href or "")
    return urllib.parse.unquote(m.group(1)) if m else (href or "")


def list_calendars(config: Config) -> list[dict[str, Any]]:
    url = caldav_client.home_url(config, "primary")
    body = '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav"><d:prop><d:displayname/><d:resourcetype/></d:prop></d:propfind>'
    _status, text = caldav_client.request(config, "PROPFIND", url, body=body, depth="1")
    records = caldav_client.parse_multistatus(text)
    email = caldav_client.account_email(config)

    calendars = []
    for rec in records:
        if CALDAV_CALENDAR_TAG not in rec.get("resourcetypes", set()):
            continue
        cal_id = _calendar_id_from_href(rec.get("href") or "")
        calendars.append(
            {
                "id": cal_id,
                "summary": rec.get("displayname") or cal_id,
                "primary": cal_id == email,
            }
        )
    return calendars


def _master_vevent(cal, uid: str | None = None):
    """Return the master VEVENT (no RECURRENCE-ID), matching ``uid`` if given."""
    vevents = list(cal.walk("VEVENT"))
    for v in vevents:
        if "RECURRENCE-ID" in v and uid is None:
            continue
        if uid is not None and str(v.get("UID")) != uid:
            continue
        if "RECURRENCE-ID" not in v:
            return v
    return vevents[0] if vevents else None


def get_event(config: Config, *, calendar_id: str = "primary", event_id: str) -> dict[str, Any]:
    url = caldav_client.event_url(config, calendar_id, event_id)
    _status, text = caldav_client.request(config, "GET", url)
    cal = icalendar.Calendar.from_ical(text)
    master = _master_vevent(cal, event_id) or _master_vevent(cal)
    if master is None:
        raise ValueError(f"Event not found: {event_id}")
    result = _event_to_dict(master, include_details=True)
    result["ics_href"] = url
    return result


# -- write helpers ------------------------------------------------------


def _new_calendar() -> icalendar.Calendar:
    cal = icalendar.Calendar()
    cal.add("PRODID", "-//Vesta//google skill CalDAV//EN")
    cal.add("VERSION", "2.0")
    return cal


def _parse_local(value: str, tz: ZoneInfo) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _set_prop(component, key: str, value) -> None:
    if key in component:
        del component[key]
    component.add(key, value)


def _build_rrule(recurrence: str, recurrence_end_date: str | None) -> dict[str, Any]:
    freq = RECURRENCE_MAP.get(recurrence, recurrence.upper())
    rule: dict[str, Any] = {"FREQ": freq}
    if recurrence_end_date:
        date_only = recurrence_end_date.split("T")[0]
        until = datetime.fromisoformat(date_only).replace(tzinfo=UTC, hour=23, minute=59, second=59)
        rule["UNTIL"] = until
    return rule


def _attendee_address(email: str, *, partstat: str = "NEEDS-ACTION") -> icalendar.vCalAddress:
    addr = icalendar.vCalAddress(f"mailto:{email}")
    addr.params["ROLE"] = icalendar.vText("REQ-PARTICIPANT")
    addr.params["PARTSTAT"] = icalendar.vText(partstat)
    addr.params["RSVP"] = icalendar.vText("TRUE")
    return addr


def create_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    subject: str,
    start: str,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    timezone: str,
    all_day: bool = False,
    recurrence: str | None = None,
    recurrence_end_date: str | None = None,
) -> dict[str, Any]:
    _validate_timezone(timezone)
    tz = ZoneInfo(timezone)
    uid = f"{uuid.uuid4().hex}@vesta-google"

    ev = icalendar.Event()
    ev.add("UID", uid)
    ev.add("DTSTAMP", datetime.now(UTC))
    ev.add("SUMMARY", subject)

    if all_day:
        start_date = date.fromisoformat(start.split("T")[0])
        end_date = date.fromisoformat(end.split("T")[0]) if end else start_date + timedelta(days=1)
        if end_date <= start_date:
            end_date = start_date + timedelta(days=1)
        ev.add("DTSTART", start_date)
        ev.add("DTEND", end_date)
    else:
        start_dt = _parse_local(start, tz)
        end_dt = _parse_local(end, tz) if end else start_dt + timedelta(hours=1)
        # Store as UTC instants so no VTIMEZONE component is needed for the PUT.
        ev.add("DTSTART", start_dt.astimezone(UTC))
        ev.add("DTEND", end_dt.astimezone(UTC))

    if location:
        ev.add("LOCATION", location)
    if body:
        ev.add("DESCRIPTION", body)
    if attendees:
        for a in attendees:
            ev.add("ATTENDEE", _attendee_address(a))
        ev.add("ORGANIZER", icalendar.vCalAddress(f"mailto:{caldav_client.account_email(config)}"))
    if recurrence:
        ev.add("RRULE", _build_rrule(recurrence, recurrence_end_date))

    cal = _new_calendar()
    cal.add_component(ev)
    ics = cal.to_ical().decode("utf-8")

    url = caldav_client.event_url(config, calendar_id, uid)
    caldav_client.request(
        config,
        "PUT",
        url,
        body=ics,
        content_type="text/calendar; charset=utf-8",
        extra_headers={"If-None-Match": "*"},
    )
    return {"status": "created", "id": uid, "calendar": calendar_id}


def update_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    if (start is not None or end is not None) and timezone is None:
        raise ValueError("--timezone is required when updating start or end")
    if timezone is not None:
        _validate_timezone(timezone)
    if all(v is None for v in (subject, start, end, location, body)):
        raise ValueError("Must specify at least one field to update")

    url = caldav_client.event_url(config, calendar_id, event_id)
    _status, text = caldav_client.request(config, "GET", url)
    cal = icalendar.Calendar.from_ical(text)
    master = _master_vevent(cal, event_id) or _master_vevent(cal)
    if master is None:
        raise ValueError(f"Event not found: {event_id}")

    tz = ZoneInfo(timezone) if timezone else UTC
    if subject is not None:
        _set_prop(master, "SUMMARY", subject)
    if start is not None:
        _set_prop(master, "DTSTART", _parse_local(start, tz).astimezone(UTC))
    if end is not None:
        _set_prop(master, "DTEND", _parse_local(end, tz).astimezone(UTC))
    if location is not None:
        _set_prop(master, "LOCATION", location)
    if body is not None:
        _set_prop(master, "DESCRIPTION", body)

    seq = master.get("SEQUENCE")
    _set_prop(master, "SEQUENCE", (int(seq) if seq is not None else 0) + 1)
    _set_prop(master, "DTSTAMP", datetime.now(UTC))

    ics = cal.to_ical().decode("utf-8")
    caldav_client.request(config, "PUT", url, body=ics, content_type="text/calendar; charset=utf-8")
    return {"status": "updated", "id": event_id, "calendar": calendar_id}


def delete_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    send_updates: str = "all",
) -> dict[str, str]:
    # CalDAV has no sendUpdates knob; Google notifies attendees on its own. The
    # send_updates arg is accepted for CLI compatibility and otherwise ignored.
    url = caldav_client.event_url(config, calendar_id, event_id)
    caldav_client.request(config, "DELETE", url)
    return {"status": "deleted", "event_id": event_id}


def respond_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict[str, str]:
    partstat = RESPONSE_TO_PARTSTAT[response]
    url = caldav_client.event_url(config, calendar_id, event_id)
    _status, text = caldav_client.request(config, "GET", url)
    cal = icalendar.Calendar.from_ical(text)
    master = _master_vevent(cal, event_id) or _master_vevent(cal)
    if master is None:
        raise ValueError(f"Event not found: {event_id}")

    raw = master.get("ATTENDEE")
    if raw is None:
        raise ValueError(f"Event {event_id} has no attendees — cannot set a response")
    items = raw if isinstance(raw, list) else [raw]

    user_email = caldav_client.account_email(config)
    found = False
    for a in items:
        if _clean_addr(a).lower() == user_email.lower():
            a.params["PARTSTAT"] = icalendar.vText(partstat)
            if message:
                a.params["X-RESPONSE-COMMENT"] = icalendar.vText(message)
            found = True
            break
    if not found:
        raise ValueError(f"You ({user_email}) are not an attendee of this event")

    del master["ATTENDEE"]
    for a in items:
        master.add("ATTENDEE", a)
    _set_prop(master, "DTSTAMP", datetime.now(UTC))

    ics = cal.to_ical().decode("utf-8")
    caldav_client.request(config, "PUT", url, body=ics, content_type="text/calendar; charset=utf-8")
    return {"status": PARTSTAT_TO_RESPONSE.get(partstat, partstat.lower()), "event_id": event_id}
