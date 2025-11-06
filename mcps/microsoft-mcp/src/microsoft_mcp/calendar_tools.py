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
        params["$select"] = "id,subject,start,end,location,body,attendees,organizer,isAllDay,recurrence,onlineMeeting,seriesMasterId"
    else:
        params["$select"] = "id,subject,start,end,location,organizer,seriesMasterId"

    # Use calendarView to get recurring event instances
    events = list(graph.request_paginated("/me/calendarView", account_id, params=params))

    return events


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
            attendees_list = [addr.strip() for addr in attendees.split(",") if addr.strip()] if "," in attendees else [attendees]
        event["attendees"] = [{"emailAddress": {"address": a}, "type": "required"} for a in attendees_list]

    result = graph.request("POST", "/me/events", account_id, json=event)
    if not result:
        raise ValueError("Failed to create event")
    return result


@mcp.tool()
def update_event(event_id: str, updates: dict[str, Any], account_id: str) -> dict[str, Any]:
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

    result = graph.request("PATCH", f"/me/events/{event_id}", account_id, json=formatted_updates)
    return result or {"status": "updated"}


@mcp.tool()
def delete_event(account_id: str, event_id: str, send_cancellation: bool = True) -> dict[str, str]:
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


