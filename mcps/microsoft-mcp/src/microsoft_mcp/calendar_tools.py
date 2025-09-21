"""Calendar-related tools for Microsoft MCP"""

import datetime as dt
from typing import Any
from .auth_tools import mcp  # Use the shared MCP instance
from . import graph


@mcp.tool()
def list_events(
    account_id: str,
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """List calendar events within specified date range, including recurring event instances"""

    now = dt.datetime.now(dt.timezone.utc)
    start = (now - dt.timedelta(days=days_back)).isoformat()
    end = (now + dt.timedelta(days=days_ahead)).isoformat()

    params = {
        "startDateTime": start,
        "endDateTime": end,
        "$orderby": "start/dateTime",
        "$top": 100,
    }

    if include_details:
        params["$select"] = (
            "id,subject,start,end,location,body,attendees,organizer,isAllDay,recurrence,onlineMeeting,seriesMasterId"
        )
    else:
        params["$select"] = "id,subject,start,end,location,organizer,seriesMasterId"

    # Use calendarView to get recurring event instances
    events = list(
        graph.request_paginated("/me/calendarView", account_id, params=params)
    )

    return events


@mcp.tool()
def get_event(event_id: str, account_id: str) -> dict[str, Any]:
    """Get full event details"""
    result = graph.request("GET", f"/me/events/{event_id}", account_id)
    if not result:
        raise ValueError(f"Event with ID {event_id} not found")
    return result


@mcp.tool()
def create_event(
    account_id: str,
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: str | list[str] | None = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """Create a calendar event

    Args:
        account_id: The account ID
        subject: Event subject/title
        start: Event start datetime (ISO format, e.g., "2024-01-15T14:00:00")
        end: Event end datetime (ISO format, e.g., "2024-01-15T15:00:00")
        location: Event location (optional)
        body: Event description (optional)
        attendees: Email addresses of attendees (optional) - accepts:
            - Single attendee: "user@example.com"
            - Multiple attendees: "user1@example.com,user2@example.com"
            - List of attendees: ["user1@example.com", "user2@example.com"]
        timezone: Timezone for the event (default: UTC)
    """
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
        if isinstance(attendees, list):
            attendees_list = attendees
        else:
            attendees_list = (
                [addr.strip() for addr in attendees.split(",") if addr.strip()]
                if "," in attendees
                else [attendees]
            )
        event["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in attendees_list
        ]

    result = graph.request("POST", "/me/events", account_id, json=event)
    if not result:
        raise ValueError("Failed to create event")
    return result


@mcp.tool()
def update_event(
    event_id: str, updates: dict[str, Any], account_id: str
) -> dict[str, Any]:
    """Update event properties"""
    formatted_updates = {}

    if "subject" in updates:
        formatted_updates["subject"] = updates["subject"]
    if "start" in updates:
        formatted_updates["start"] = {
            "dateTime": updates["start"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    if "end" in updates:
        formatted_updates["end"] = {
            "dateTime": updates["end"],
            "timeZone": updates.get("timezone", "UTC"),
        }
    if "location" in updates:
        formatted_updates["location"] = {"displayName": updates["location"]}
    if "body" in updates:
        formatted_updates["body"] = {"contentType": "Text", "content": updates["body"]}

    result = graph.request(
        "PATCH", f"/me/events/{event_id}", account_id, json=formatted_updates
    )
    return result or {"status": "updated"}


@mcp.tool()
def delete_event(
    account_id: str, event_id: str, send_cancellation: bool = True
) -> dict[str, str]:
    """Delete or cancel a calendar event"""

    if send_cancellation:
        graph.request("POST", f"/me/events/{event_id}/cancel", account_id, json={})
    else:
        graph.request("DELETE", f"/me/events/{event_id}", account_id)
    return {"status": "deleted"}


@mcp.tool()
def respond_event(
    account_id: str,
    event_id: str,
    response: str = "accept",
    message: str | None = None,
) -> dict[str, str]:
    """Respond to event invitation (accept, decline, tentativelyAccept)"""
    payload: dict[str, Any] = {"sendResponse": True}
    if message:
        payload["comment"] = message

    graph.request("POST", f"/me/events/{event_id}/{response}", account_id, json=payload)
    return {"status": response}


@mcp.tool()
def check_availability(
    account_id: str,
    start: str,
    end: str,
    attendees: str | list[str] | None = None,
) -> dict[str, Any]:
    """Check calendar availability for scheduling

    Args:
        account_id: The account ID
        start: Start datetime (ISO format, e.g., "2024-01-15T14:00:00")
        end: End datetime (ISO format, e.g., "2024-01-15T18:00:00")
        attendees: Email addresses to check availability for (optional) - accepts:
            - Single person: "user@example.com"
            - Multiple people: "user1@example.com,user2@example.com"
            - List of attendees: ["user1@example.com", "user2@example.com"]
    """
    me_info = graph.request("GET", "/me", account_id)
    if not me_info or "mail" not in me_info:
        raise ValueError("Failed to get user email address")
    schedules = [me_info["mail"]]
    if attendees:
        if isinstance(attendees, list):
            attendees_list = attendees
        else:
            attendees_list = (
                [addr.strip() for addr in attendees.split(",") if addr.strip()]
                if "," in attendees
                else [attendees]
            )
        schedules.extend(attendees_list)

    payload = {
        "schedules": schedules,
        "startTime": {"dateTime": start, "timeZone": "UTC"},
        "endTime": {"dateTime": end, "timeZone": "UTC"},
        "availabilityViewInterval": 30,
    }

    result = graph.request("POST", "/me/calendar/getSchedule", account_id, json=payload)
    if not result:
        raise ValueError("Failed to check availability")
    return result


@mcp.tool()
def search_events(
    query: str,
    account_id: str,
    days_ahead: int = 365,
    days_back: int = 365,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Search calendar events using the modern search API."""

    events = list(graph.search_query(query, ["event"], account_id, limit))

    # Filter by date range if needed
    if days_ahead != 365 or days_back != 365:
        now = dt.datetime.now(dt.timezone.utc)
        start = now - dt.timedelta(days=days_back)
        end = now + dt.timedelta(days=days_ahead)

        filtered_events = []
        for event in events:
            event_start = dt.datetime.fromisoformat(
                event.get("start", {}).get("dateTime", "").replace("Z", "+00:00")
            )
            event_end = dt.datetime.fromisoformat(
                event.get("end", {}).get("dateTime", "").replace("Z", "+00:00")
            )

            if event_start <= end and event_end >= start:
                filtered_events.append(event)

        return filtered_events

    return events
