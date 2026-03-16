import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import api
from .config import Config


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: '{timezone}'. Use IANA names like 'Europe/London' or 'America/New_York'.")


RECURRENCE_MAP = {
    "daily": "DAILY",
    "weekly": "WEEKLY",
    "monthly": "MONTHLY",
    "yearly": "YEARLY",
}

RESPONSE_MAP = {
    "accept": "accepted",
    "decline": "declined",
    "tentative": "tentativelyAccepted",
}


def _get_time_range(days_ahead: int, days_back: int, user_timezone: str | None = None) -> tuple[str, str]:
    tz = ZoneInfo(user_timezone) if user_timezone else dt.UTC

    now_local = dt.datetime.now(tz)
    start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = start_of_today - dt.timedelta(days=days_back)
    end_dt = start_of_today + dt.timedelta(days=days_ahead + 1)

    return (
        start_dt.astimezone(dt.UTC).isoformat(),
        end_dt.astimezone(dt.UTC).isoformat(),
    )


def list_events(
    config: Config,
    *,
    calendar_id: str = "primary",
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
    user_timezone: str | None = None,
) -> list[dict[str, Any]]:
    service = api.calendar_service(config)
    time_min, time_max = _get_time_range(days_ahead, days_back, user_timezone)

    events_result = api.retry(
        lambda: (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=250,
            )
            .execute()
        )
    )

    events = events_result["items"] if "items" in events_result else []

    if not include_details:
        return [
            {
                "id": e["id"],
                "summary": e["summary"] if "summary" in e else "",
                "start": e["start"] if "start" in e else {},
                "end": e["end"] if "end" in e else {},
                "location": e["location"] if "location" in e else None,
            }
            for e in events
        ]
    return events


def list_calendars(config: Config) -> list[dict[str, Any]]:
    service = api.calendar_service(config)
    result = api.retry(lambda: service.calendarList().list().execute())
    return [
        {
            "id": cal["id"],
            "summary": cal["summary"] if "summary" in cal else "",
            "primary": cal["primary"] if "primary" in cal else False,
            "accessRole": cal["accessRole"] if "accessRole" in cal else "",
        }
        for cal in (result["items"] if "items" in result else [])
    ]


def get_event(config: Config, *, calendar_id: str = "primary", event_id: str) -> dict[str, Any]:
    service = api.calendar_service(config)
    return api.retry(lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute())


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
    meet_link: bool = False,
) -> dict[str, Any]:
    _validate_timezone(timezone)
    service = api.calendar_service(config)

    start_date = start.split("T")[0] if "T" in start else start

    event: dict[str, Any] = {"summary": subject}

    if all_day:
        end_date = end.split("T")[0] if end and "T" in end else (end or start_date)
        if end_date == start_date:
            end_dt = dt.date.fromisoformat(start_date) + dt.timedelta(days=1)
            end_date = end_dt.isoformat()
        event["start"] = {"date": start_date, "timeZone": timezone}
        event["end"] = {"date": end_date, "timeZone": timezone}
    else:
        if not end:
            start_dt = dt.datetime.fromisoformat(start)
            end_iso = (start_dt + dt.timedelta(hours=1)).isoformat()
        else:
            end_iso = end
        event["start"] = {"dateTime": start, "timeZone": timezone}
        event["end"] = {"dateTime": end_iso, "timeZone": timezone}

    if location:
        event["location"] = location
    if body:
        event["description"] = body
    if attendees:
        event["attendees"] = [{"email": a} for a in attendees]

    if recurrence:
        freq = RECURRENCE_MAP[recurrence] if recurrence in RECURRENCE_MAP else recurrence.upper()
        rule = f"RRULE:FREQ={freq}"
        if recurrence_end_date:
            date_only = recurrence_end_date.split("T")[0] if "T" in recurrence_end_date else recurrence_end_date
            until = date_only.replace("-", "")
            rule += f";UNTIL={until}"
        event["recurrence"] = [rule]

    if meet_link:
        event["conferenceData"] = {
            "createRequest": {
                "requestId": str(uuid.uuid4()),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }

    insert_kwargs: dict[str, Any] = {"calendarId": calendar_id, "body": event}
    if meet_link:
        insert_kwargs["conferenceDataVersion"] = 1

    return api.retry(lambda: service.events().insert(**insert_kwargs).execute())


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

    service = api.calendar_service(config)
    updates: dict[str, Any] = {}

    if subject is not None:
        updates["summary"] = subject
    if start is not None:
        updates["start"] = {"dateTime": start, "timeZone": timezone}
    if end is not None:
        updates["end"] = {"dateTime": end, "timeZone": timezone}
    if location is not None:
        updates["location"] = location
    if body is not None:
        updates["description"] = body

    if not updates:
        raise ValueError("Must specify at least one field to update")

    return api.retry(lambda: service.events().patch(calendarId=calendar_id, eventId=event_id, body=updates).execute())


def delete_event(config: Config, *, calendar_id: str = "primary", event_id: str, send_updates: str = "all") -> dict[str, str]:
    service = api.calendar_service(config)
    api.retry(lambda: service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates=send_updates).execute())
    return {"status": "deleted", "event_id": event_id}


def respond_event(
    config: Config,
    *,
    calendar_id: str = "primary",
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict[str, str]:
    service = api.calendar_service(config)
    event = api.retry(lambda: service.events().get(calendarId=calendar_id, eventId=event_id).execute())

    attendees = event["attendees"] if "attendees" in event else []
    if not attendees:
        raise ValueError(f"Event {event_id} has no attendees — cannot set response")

    creds = api.auth.get_credentials(config.token_file, config.credentials_file, config.scopes)
    user_email = api.auth.get_user_email(creds)

    response_status = RESPONSE_MAP[response] if response in RESPONSE_MAP else response

    found = False
    for attendee in attendees:
        email = attendee["email"] if "email" in attendee else ""
        if email.lower() == user_email.lower() or ("self" in attendee and attendee["self"]):
            attendee["responseStatus"] = response_status
            if message:
                attendee["comment"] = message
            found = True
            break

    if not found:
        raise ValueError(f"You ({user_email}) are not an attendee of this event")

    api.retry(lambda: service.events().patch(calendarId=calendar_id, eventId=event_id, body={"attendees": attendees}).execute())
    return {"status": response_status, "event_id": event_id}
