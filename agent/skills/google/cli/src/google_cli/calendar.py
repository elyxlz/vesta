#!/usr/bin/env python3
"""Google Calendar on the official REST API (calendar/v3).

Talks to the Calendar API directly over stdlib ``urllib`` with the OAuth Bearer
token from this skill's token store. The user's own Google Cloud project (see
SETUP.md) must have the Google Calendar API enabled. Event ids are Calendar API
event ids. All API traffic funnels through :func:`_http` so tests can
monkeypatch a single choke point.

NOTE ON INVITES: creating/updating/deleting an event with attendees causes Google
to email calendar invites/updates to them, a real outward send. The
EMAIL_DRAFT_ONLY guard covers email sending only and does NOT block calendar
writes; use judgment before writing events with attendees.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import auth
from .config import Config

CAL_API_BASE = "https://www.googleapis.com/calendar/v3"
HTTP_TIMEOUT_SECS = 30
LIST_MAX_RESULTS = 250

RECURRENCE_MAP = {
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
    "yearly": "YEARLY",
}

RESPONSE_TO_STATUS = {
    "accept": "accepted",
    "decline": "declined",
    "tentative": "tentative",
}


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        raise ValueError(f"Invalid timezone: '{timezone}'. Use IANA names like 'Europe/London' or 'America/New_York'.")


# -- HTTP layer (single choke point) -------------------------------------


def _bearer(config: Config) -> str:
    creds = auth.get_credentials(config.token_file, config.credentials_file, config.scopes)
    return creds.token


def _http(config: Config, method: str, path: str, *, params: dict | None = None, body: dict | None = None) -> dict:
    """Make one Calendar API request and return parsed JSON ({} if empty)."""
    url = CAL_API_BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {_bearer(config)}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECS) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        if "accessNotConfigured" in detail or "has not been used in project" in detail:
            raise RuntimeError(
                f"The Google Calendar API is not enabled on your Google Cloud project (HTTP {e.code}). "
                f"Enable it at https://console.cloud.google.com/apis/library/calendar-json.googleapis.com "
                f"and retry. (details: {detail[:300]})"
            )
        if e.code in (401, 403):
            raise RuntimeError(
                f"Google Calendar refused the request (HTTP {e.code}). The stored token is missing scopes "
                "or was minted under a different OAuth client; run 'google auth login' to sign in again. "
                f"(details: {detail[:300]})"
            )
        raise RuntimeError(f"Google Calendar API error {e.code}: {detail[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Google Calendar {method} could not reach Google: {e.reason}")


def _events_path(calendar_id: str) -> str:
    return f"/calendars/{urllib.parse.quote(calendar_id, safe='')}/events"


def _event_path(calendar_id: str, event_id: str) -> str:
    return _events_path(calendar_id) + "/" + urllib.parse.quote(event_id, safe="")


# -- shaping --------------------------------------------------------------


def _rfc3339(when: datetime) -> str:
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _event_to_dict(event: dict, *, include_details: bool) -> dict:
    result: dict = {
        "id": event["id"] if "id" in event else None,
        "summary": event["summary"] if "summary" in event else "",
        "start": event["start"] if "start" in event else {},
        "end": event["end"] if "end" in event else {},
        "location": event["location"] if "location" in event else None,
        "status": event["status"] if "status" in event else None,
    }
    if include_details:
        result["description"] = event["description"] if "description" in event else None
        result["organizer"] = event["organizer"] if "organizer" in event else None
        result["attendees"] = event["attendees"] if "attendees" in event else []
        if "recurrence" in event:
            result["recurrence"] = event["recurrence"]
        if "recurringEventId" in event:
            result["recurringEventId"] = event["recurringEventId"]
    return result


def _time_field(value: str, timezone: str) -> dict:
    """Build a Calendar API start/end object: timed dateTime with timeZone, or an all-day date."""
    if "T" in value:
        return {"dateTime": value, "timeZone": timezone}
    return {"date": value}


# -- commands -------------------------------------------------------------


def list_events_between(
    config: Config,
    *,
    calendar_id: str = "primary",
    start: datetime,
    end: datetime,
    include_details: bool = True,
    user_timezone: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return events overlapping ``[start, end)``, recurring ones expanded (singleEvents)."""
    if user_timezone:
        _validate_timezone(user_timezone)
    params = {
        "timeMin": _rfc3339(start),
        "timeMax": _rfc3339(end),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": min(limit, LIST_MAX_RESULTS) if limit is not None else LIST_MAX_RESULTS,
        "timeZone": user_timezone,
    }
    result = _http(config, "GET", _events_path(calendar_id), params=params)
    items = result["items"] if "items" in result else []
    if limit is not None:
        items = items[:limit]
    return [_event_to_dict(e, include_details=include_details) for e in items]


def list_events(
    config: Config,
    *,
    calendar_id: str = "primary",
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
    user_timezone: str | None = None,
    limit: int | None = None,
) -> list[dict]:
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


def list_calendars(config: Config) -> list[dict]:
    result = _http(config, "GET", "/users/me/calendarList")
    items = result["items"] if "items" in result else []
    return [
        {
            "id": c["id"] if "id" in c else None,
            "summary": c["summary"] if "summary" in c else "",
            "primary": c["primary"] if "primary" in c else False,
            "accessRole": c["accessRole"] if "accessRole" in c else "",
        }
        for c in items
    ]


def get_event(config: Config, *, calendar_id: str = "primary", event_id: str) -> dict:
    return _http(config, "GET", _event_path(calendar_id, event_id))


def _build_rrule(recurrence: str, recurrence_end_date: str | None) -> str:
    freq = RECURRENCE_MAP[recurrence] if recurrence in RECURRENCE_MAP else recurrence.upper()
    rule = f"RRULE:FREQ={freq}"
    if recurrence_end_date:
        date_only = recurrence_end_date.split("T")[0]
        until = datetime.fromisoformat(date_only).replace(tzinfo=UTC, hour=23, minute=59, second=59)
        rule += ";UNTIL=" + until.strftime("%Y%m%dT%H%M%SZ")
    return rule


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
) -> dict:
    _validate_timezone(timezone)

    if all_day:
        start_date = date.fromisoformat(start.split("T")[0])
        end_date = date.fromisoformat(end.split("T")[0]) if end else start_date + timedelta(days=1)
        # The Calendar API's all-day end date is exclusive; bump a same-day end.
        if end_date <= start_date:
            end_date = start_date + timedelta(days=1)
        event: dict = {
            "summary": subject,
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
    else:
        end_value = end
        if not end_value:
            end_value = (datetime.fromisoformat(start) + timedelta(hours=1)).isoformat()
        event = {
            "summary": subject,
            "start": _time_field(start, timezone),
            "end": _time_field(end_value, timezone),
        }

    if location:
        event["location"] = location
    if body:
        event["description"] = body
    if attendees:
        event["attendees"] = [{"email": a} for a in attendees]
    if recurrence:
        event["recurrence"] = [_build_rrule(recurrence, recurrence_end_date)]

    created = _http(config, "POST", _events_path(calendar_id), params={"sendUpdates": "all"}, body=event)
    return {"status": "created", "id": created["id"] if "id" in created else None, "calendar": calendar_id}


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
) -> dict:
    if (start is not None or end is not None) and timezone is None:
        raise ValueError("--timezone is required when updating start or end")
    if timezone is not None:
        _validate_timezone(timezone)
    if all(v is None for v in (subject, start, end, location, body)):
        raise ValueError("Must specify at least one field to update")

    updates: dict = {}
    if subject is not None:
        updates["summary"] = subject
    if start is not None:
        updates["start"] = _time_field(start, timezone or "UTC")
    if end is not None:
        updates["end"] = _time_field(end, timezone or "UTC")
    if location is not None:
        updates["location"] = location
    if body is not None:
        updates["description"] = body

    _http(config, "PATCH", _event_path(calendar_id, event_id), params={"sendUpdates": "all"}, body=updates)
    return {"status": "updated", "id": event_id, "calendar": calendar_id}


def delete_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    send_updates: str = "all",
) -> dict:
    _http(config, "DELETE", _event_path(calendar_id, event_id), params={"sendUpdates": send_updates})
    return {"status": "deleted", "event_id": event_id}


def respond_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict:
    status = RESPONSE_TO_STATUS[response]
    event = _http(config, "GET", _event_path(calendar_id, event_id))
    attendees = event["attendees"] if "attendees" in event else []
    if not attendees:
        raise ValueError(f"Event {event_id} has no attendees - cannot set a response")

    # The API stamps self=True on the authenticated user's own attendee entry.
    found = False
    for a in attendees:
        if "self" in a and a["self"]:
            a["responseStatus"] = status
            if message:
                a["comment"] = message
            found = True
            break
    if not found:
        raise ValueError("You are not an attendee of this event")

    _http(config, "PATCH", _event_path(calendar_id, event_id), params={"sendUpdates": "all"}, body={"attendees": attendees})
    return {"status": status, "event_id": event_id}
