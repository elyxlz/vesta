"""Calendar commands for Microsoft CLI."""

import datetime as dt
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from . import graph, auth
from .config import Config
from .settings import MicrosoftSettings


def _validate_timezone(timezone: str) -> None:
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, KeyError):
        raise ValueError(f"Invalid timezone: '{timezone}'. Use IANA names like 'Europe/London' or 'America/New_York'.")


def _get_settings() -> MicrosoftSettings:
    return MicrosoftSettings()


def _get_calendar_day_range(
    days_ahead: int,
    days_back: int,
    user_timezone: str | None = None,
) -> tuple[str, str]:
    try:
        tz = ZoneInfo(user_timezone) if user_timezone else dt.UTC
    except Exception:
        tz = dt.UTC

    now_local = dt.datetime.now(tz)
    start_of_today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    start_datetime = start_of_today - dt.timedelta(days=days_back)
    end_datetime = start_of_today + dt.timedelta(days=days_ahead + 1)

    start_utc = start_datetime.astimezone(dt.UTC).replace(microsecond=0)
    end_utc = end_datetime.astimezone(dt.UTC).replace(microsecond=0)

    return (
        start_utc.isoformat().replace("+00:00", "Z"),
        end_utc.isoformat().replace("+00:00", "Z"),
    )


def _get_calendar_id_by_name(
    config: Config,
    client: httpx.Client,
    account_id: str,
    calendar_name: str,
) -> str:
    settings = _get_settings()
    calendars = list(
        graph.request_paginated(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "/me/calendars",
            account_id,
            params={"$select": "id,name"},
        )
    )
    name_lower = calendar_name.lower()
    for cal in calendars:
        if cal["name"].lower() == name_lower:
            return cal["id"]
    available = ", ".join(f"'{c['name']}'" for c in calendars)
    raise ValueError(f"Calendar '{calendar_name}' not found. Available: {available}")


def list_events(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    calendar_name: str | None = None,
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
    user_timezone: str | None = None,
) -> list[dict[str, Any]]:
    settings = _get_settings()

    try:
        account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

        if include_details:
            select = "id,subject,start,end,location,body,attendees,organizer,isAllDay,recurrence,onlineMeeting,seriesMasterId"
        else:
            select = "id,subject,start,end,location,organizer,seriesMasterId"

        if calendar_name:
            calendar_id = _get_calendar_id_by_name(config, client, account_id, calendar_name)
            params = {"$select": select, "$top": 100, "$orderby": "start/dateTime"}
            endpoint = f"/me/calendars/{calendar_id}/events"
        else:
            start, end = _get_calendar_day_range(days_ahead, days_back, user_timezone)
            params = {
                "startDateTime": start,
                "endDateTime": end,
                "$orderby": "start/dateTime",
                "$top": 100,
                "$select": select,
            }
            endpoint = "/me/calendarView"

        events = list(
            graph.request_paginated(
                client,
                config.cache_file,
                config.scopes,
                settings,
                config.base_url,
                endpoint,
                account_id,
                params=params,
            )
        )

        return events

    except Exception as e:
        raise ValueError(f"Failed to list calendar events for {account_email}: {e}") from e


def list_calendars(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
) -> list[dict[str, Any]]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    calendars = list(
        graph.request_paginated(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "/me/calendars",
            account_id,
            params={"$select": "id,name,color,isDefaultCalendar"},
        )
    )
    return calendars


def get_event(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    event_id: str,
) -> dict[str, Any]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    result = graph.request(client, config.cache_file, config.scopes, settings, config.base_url, "GET", f"/me/events/{event_id}", account_id)
    if not result:
        raise ValueError(f"Event '{event_id}' not found")
    return result


def create_event(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    subject: str,
    start: str,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    timezone: str,
    calendar_name: str | None = None,
    is_all_day: bool = False,
    recurrence: str | None = None,
    recurrence_end_date: str | None = None,
) -> dict[str, Any]:
    _validate_timezone(timezone)
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    calendar_id = _get_calendar_id_by_name(config, client, account_id, calendar_name) if calendar_name else None

    start_date = start.split("T")[0] if "T" in start else start

    if is_all_day:
        end_date = end.split("T")[0] if end and "T" in end else (end or start_date)
        if end_date == start_date:
            end_dt = dt.date.fromisoformat(start_date) + dt.timedelta(days=1)
            end_date = end_dt.isoformat()
        event: dict[str, Any] = {
            "subject": subject,
            "isAllDay": True,
            "start": {"dateTime": start_date, "timeZone": timezone},
            "end": {"dateTime": end_date, "timeZone": timezone},
        }
    else:
        if not end:
            raise ValueError("end is required for non-all-day events")
        event = {
            "subject": subject,
            "start": {"dateTime": start, "timeZone": timezone},
            "end": {"dateTime": end, "timeZone": timezone},
        }

    if location:
        event["location"] = {"displayName": location}

    if body:
        event["body"] = {"contentType": "Text", "content": body}

    if attendees:
        event["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees]

    if recurrence:
        parsed_date = dt.date.fromisoformat(start_date)

        pattern: dict[str, Any] = {"interval": 1}
        if recurrence == "daily":
            pattern["type"] = "daily"
        elif recurrence == "weekly":
            pattern["type"] = "weekly"
            pattern["daysOfWeek"] = [parsed_date.strftime("%A").lower()]
        elif recurrence == "monthly":
            pattern["type"] = "absoluteMonthly"
            pattern["dayOfMonth"] = parsed_date.day
        elif recurrence == "yearly":
            pattern["type"] = "absoluteYearly"
            pattern["dayOfMonth"] = parsed_date.day
            pattern["month"] = parsed_date.month

        recurrence_range: dict[str, Any] = {"startDate": start_date}
        if recurrence_end_date:
            recurrence_range["type"] = "endDate"
            recurrence_range["endDate"] = recurrence_end_date
        else:
            recurrence_range["type"] = "noEnd"

        event["recurrence"] = {"pattern": pattern, "range": recurrence_range}

    endpoint = f"/me/calendars/{calendar_id}/events" if calendar_id else "/me/events"

    result = graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "POST",
        endpoint,
        account_id,
        json=event,
    )
    if not result:
        raise ValueError("Failed to create event")
    return result


def update_event(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    event_id: str,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
    body: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    if (start is not None or end is not None) and timezone is None:
        raise ValueError("timezone is required when updating start or end")
    if timezone is not None:
        _validate_timezone(timezone)

    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)
    formatted_updates: dict[str, Any] = {}

    if subject is not None:
        formatted_updates["subject"] = subject
    if start is not None:
        formatted_updates["start"] = {"dateTime": start, "timeZone": timezone}
    if end is not None:
        formatted_updates["end"] = {"dateTime": end, "timeZone": timezone}
    if location is not None:
        formatted_updates["location"] = {"displayName": location}
    if body is not None:
        formatted_updates["body"] = {"contentType": "Text", "content": body}

    if not formatted_updates:
        raise ValueError("Must specify at least one field to update")

    result = graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "PATCH",
        f"/me/events/{event_id}",
        account_id,
        json=formatted_updates,
    )
    return result or {"status": "updated"}


def delete_event(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    event_id: str,
    send_cancellation: bool = True,
) -> dict[str, str]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)

    if send_cancellation:
        graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "POST",
            f"/me/events/{event_id}/cancel",
            account_id,
            json={},
        )
    else:
        graph.request(
            client,
            config.cache_file,
            config.scopes,
            settings,
            config.base_url,
            "DELETE",
            f"/me/events/{event_id}",
            account_id,
        )
    return {"status": "deleted", "event_id": event_id}


def respond_event(
    config: Config,
    client: httpx.Client,
    *,
    account_email: str,
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict[str, str]:
    settings = _get_settings()
    account_id = auth.get_account_id_by_email(account_email, config.cache_file, settings=settings)
    payload: dict[str, Any] = {"sendResponse": True}
    if message:
        payload["comment"] = message

    graph.request(
        client,
        config.cache_file,
        config.scopes,
        settings,
        config.base_url,
        "POST",
        f"/me/events/{event_id}/{response}",
        account_id,
        json=payload,
    )
    return {"status": response}
