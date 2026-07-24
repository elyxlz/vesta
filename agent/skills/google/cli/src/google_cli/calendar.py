#!/usr/bin/env python3
"""Google Calendar on the official REST API (calendar/v3).

Drives the API through google-api-python-client (``build("calendar", "v3")``,
same as the Gmail side in :mod:`api`), which owns auth refresh and the HTTP
plumbing. The user's own Google Cloud project (see SETUP.md) must have the
Google Calendar API enabled. Event ids are Calendar API event ids. Each command
builds one service (one credential resolution) and funnels every request through
:func:`_execute`, the single choke point for tests and for mapping API errors to
actionable messages.

NOTE ON INVITES: creating/updating/deleting an event with attendees causes Google
to email calendar invites/updates to them, a real outward send. The
EMAIL_DRAFT_ONLY guard covers email sending only and does NOT block calendar
writes; use judgment before writing events with attendees. ``respond`` is the
exception: an RSVP never fans out to the guest list.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from googleapiclient.errors import HttpError

from . import api
from .config import Config

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

RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}

ACCESS_NOT_CONFIGURED_MESSAGE = (
    "Google Calendar refused the request (HTTP {code}): the Calendar API is not enabled on the Cloud project "
    "of the OAuth client this token was minted under. If you signed in before the bring-your-own-client switch, "
    "the token belongs to the shared Thunderbird client, whose project has the Calendar API permanently disabled: "
    "place your own client JSON at ~/.google/credentials.json (see SETUP.md) and run 'google auth login' to "
    "re-authenticate under it. If you already signed in with your own client, enable the Calendar API at "
    "https://console.cloud.google.com/apis/library/calendar-json.googleapis.com and retry. (details: {detail})"
)

REAUTH_MESSAGE = (
    "Google Calendar refused the request (HTTP {code}). The stored token is missing scopes or no longer valid; "
    "run 'google auth login' to sign in again (requires ~/.google/credentials.json, see SETUP.md). "
    "(details: {detail})"
)


class CalendarAuthError(RuntimeError):
    """The Calendar API rejected the credentials; user action (re-auth or API enablement) is needed."""


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError) as e:
        raise ValueError(f"Invalid timezone: '{timezone}'. Use IANA names like 'Europe/London' or 'America/New_York'.") from e


# -- request execution (single choke point) --------------------------------


def _error_reason(detail: str) -> str:
    """Extract the first ``errors[].reason`` from a Calendar API error body."""
    try:
        parsed = json.loads(detail)
    except ValueError:
        return ""
    if not isinstance(parsed, dict) or "error" not in parsed or not isinstance(parsed["error"], dict):
        return ""
    error = parsed["error"]
    errors = error["errors"] if "errors" in error else []
    if isinstance(errors, list) and errors and isinstance(errors[0], dict) and "reason" in errors[0]:
        return str(errors[0]["reason"])
    return ""


def _api_error(code: int, detail: str) -> RuntimeError:
    reason = _error_reason(detail)
    if reason in RATE_LIMIT_REASONS:
        return RuntimeError(f"Google Calendar rate/quota limit hit (HTTP {code}, {reason}); retry later. (details: {detail[:300]})")
    if reason == "accessNotConfigured" or "accessNotConfigured" in detail or "has not been used in project" in detail:
        return CalendarAuthError(ACCESS_NOT_CONFIGURED_MESSAGE.format(code=code, detail=detail[:300]))
    if code in (401, 403):
        return CalendarAuthError(REAUTH_MESSAGE.format(code=code, detail=detail[:300]))
    return RuntimeError(f"Google Calendar API error {code}: {detail[:500]}")


def _execute(request) -> dict:
    """Run one Calendar API request, mapping HttpError to an actionable message."""
    try:
        result = request.execute()
    except HttpError as e:
        detail = e.content.decode(errors="replace") if isinstance(e.content, bytes) else str(e.content)
        raise _api_error(e.resp.status, detail) from e
    return result if isinstance(result, dict) else {}


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


def _patch_time_field(value: str, timezone: str) -> dict:
    """Time field for PATCH: explicitly null the sibling key, since patch semantics
    keep an omitted subfield and the value type could not flip between timed and all-day."""
    if "T" in value:
        return {"dateTime": value, "timeZone": timezone, "date": None}
    return {"date": value, "dateTime": None, "timeZone": None}


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
    """Return events overlapping ``[start, end)``, recurring ones expanded (singleEvents), all pages."""
    if user_timezone:
        _validate_timezone(user_timezone)
    service = api.calendar_service(config)
    page_size = min(limit, LIST_MAX_RESULTS) if limit is not None else LIST_MAX_RESULTS
    items: list[dict] = []
    page_token: str | None = None
    while True:
        params: dict = {
            "calendarId": calendar_id,
            "timeMin": _rfc3339(start),
            "timeMax": _rfc3339(end),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": page_size,
        }
        if user_timezone:
            params["timeZone"] = user_timezone
        if page_token:
            params["pageToken"] = page_token
        result = _execute(service.events().list(**params))
        items.extend(result["items"] if "items" in result else [])
        if limit is not None and len(items) >= limit:
            items = items[:limit]
            break
        page_token = result["nextPageToken"] if "nextPageToken" in result else None
        if not page_token:
            break
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
    if user_timezone:
        _validate_timezone(user_timezone)
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
    result = _execute(api.calendar_service(config).calendarList().list())
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
    event = _execute(api.calendar_service(config).events().get(calendarId=calendar_id, eventId=event_id))
    return _event_to_dict(event, include_details=True)


def _build_rrule(recurrence: str, recurrence_end_date: str | None, *, all_day: bool) -> str:
    freq = RECURRENCE_MAP[recurrence] if recurrence in RECURRENCE_MAP else recurrence.upper()
    rule = f"RRULE:FREQ={freq}"
    if recurrence_end_date:
        date_only = recurrence_end_date.split("T")[0]
        # RFC 5545: UNTIL's value type must match DTSTART's (DATE for all-day, DATE-TIME otherwise).
        if all_day:
            rule += ";UNTIL=" + date_only.replace("-", "")
        else:
            until = datetime.fromisoformat(date_only).replace(tzinfo=UTC, hour=23, minute=59, second=59)
            rule += ";UNTIL=" + until.strftime("%Y%m%dT%H%M%SZ")
    return rule


@dataclass
class NewEvent:
    """User-facing fields of an event to create; the API payload is derived from it."""

    subject: str
    start: str
    timezone: str
    end: str | None = None
    location: str | None = None
    body: str | None = None
    attendees: list[str] | None = None
    all_day: bool = False
    recurrence: str | None = None
    recurrence_end_date: str | None = None


def create_event(config: Config, event: NewEvent, *, calendar_id: str = "primary") -> dict:
    _validate_timezone(event.timezone)
    # A date-only start is an all-day event even without --all-day; a mixed
    # date/dateTime start-end pair would be rejected by the API.
    all_day = event.all_day or "T" not in event.start

    if all_day:
        start_date = date.fromisoformat(event.start.split("T", maxsplit=1)[0])
        end_date = date.fromisoformat(event.end.split("T")[0]) if event.end else start_date + timedelta(days=1)
        # The Calendar API's all-day end date is exclusive; bump a same-day end.
        if end_date <= start_date:
            end_date = start_date + timedelta(days=1)
        payload: dict = {
            "summary": event.subject,
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
    else:
        end_value = event.end
        if not end_value:
            end_value = (datetime.fromisoformat(event.start) + timedelta(hours=1)).isoformat()
        payload = {
            "summary": event.subject,
            "start": _time_field(event.start, event.timezone),
            "end": _time_field(end_value, event.timezone),
        }

    if event.location:
        payload["location"] = event.location
    if event.body:
        payload["description"] = event.body
    if event.attendees:
        payload["attendees"] = [{"email": a} for a in event.attendees]
    if event.recurrence:
        payload["recurrence"] = [_build_rrule(event.recurrence, event.recurrence_end_date, all_day=all_day)]

    created = _execute(api.calendar_service(config).events().insert(calendarId=calendar_id, body=payload, sendUpdates="all"))
    return {"status": "created", "id": created["id"] if "id" in created else None, "calendar": calendar_id}


def _resolve_series(service, calendar_id: str, event_id: str) -> tuple[str, dict]:
    """Fetch the event; an occurrence id (singleEvents expansion) resolves to its series master.

    Returns ``(target_event_id, fetched_event)`` so update/delete address the whole
    series, matching how a listed recurring event behaves elsewhere in this skill.
    """
    event = _execute(service.events().get(calendarId=calendar_id, eventId=event_id))
    if "recurringEventId" in event:
        return event["recurringEventId"], event
    return event_id, event


@dataclass
class EventPatch:
    """Fields of an existing event to change; None means leave untouched."""

    subject: str | None = None
    start: str | None = None
    end: str | None = None
    location: str | None = None
    body: str | None = None
    timezone: str | None = None


def update_event(config: Config, patch: EventPatch, *, calendar_id: str = "primary", event_id: str) -> dict:
    if all(v is None for v in (patch.subject, patch.start, patch.end, patch.location, patch.body)):
        raise ValueError("Must specify at least one field to update")

    updates: dict = {}
    if patch.subject is not None:
        updates["summary"] = patch.subject
    if patch.location is not None:
        updates["location"] = patch.location
    if patch.body is not None:
        updates["description"] = patch.body
    if patch.start is not None or patch.end is not None:
        if patch.timezone is None:
            raise ValueError("--timezone is required when updating start or end")
        _validate_timezone(patch.timezone)
        if patch.start is not None:
            updates["start"] = _patch_time_field(patch.start, patch.timezone)
        if patch.end is not None:
            updates["end"] = _patch_time_field(patch.end, patch.timezone)

    service = api.calendar_service(config)
    target_id, existing = _resolve_series(service, calendar_id, event_id)

    # Keep start/end value types matched: patching one side to a different type
    # than the other (date vs dateTime) is rejected by the API.
    if (patch.start is None) != (patch.end is None):
        provided = patch.start if patch.start is not None else patch.end
        other = existing["end"] if patch.start is not None else existing["start"]
        if provided is not None and ("T" not in provided) != ("date" in other):
            raise ValueError("start and end must both be all-day dates or both be timed dateTimes; pass both --start and --end")

    _execute(service.events().patch(calendarId=calendar_id, eventId=target_id, body=updates, sendUpdates="all"))
    return {"status": "updated", "id": target_id, "calendar": calendar_id}


def delete_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    send_updates: str = "all",
) -> dict:
    service = api.calendar_service(config)
    target_id, _existing = _resolve_series(service, calendar_id, event_id)
    _execute(service.events().delete(calendarId=calendar_id, eventId=target_id, sendUpdates=send_updates))
    return {"status": "deleted", "event_id": target_id}


def respond_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict:
    status = RESPONSE_TO_STATUS[response]
    service = api.calendar_service(config)
    event = _execute(service.events().get(calendarId=calendar_id, eventId=event_id))
    attendees = event["attendees"] if "attendees" in event else []
    if not attendees:
        raise ValueError(f"Event {event_id} has no attendees - cannot set a response")

    # The API stamps self=True on the authenticated user's own attendee entry.
    found = False
    for a in attendees:
        if "self" not in a or not a["self"]:
            continue
        a["responseStatus"] = status
        if message:
            a["comment"] = message
        found = True
        break
    if not found:
        raise ValueError("You are not an attendee of this event")

    # sendUpdates=none: an RSVP must not email the whole guest list; the
    # organizer sees the response on their own calendar copy.
    _execute(service.events().patch(calendarId=calendar_id, eventId=event_id, body={"attendees": attendees}, sendUpdates="none"))
    return {"status": status, "event_id": event_id}
