"""Calendar-related tools for Microsoft MCP"""

import datetime as dt
from typing import Any, Literal
from mcp.server.fastmcp import Context
from .auth_tools import mcp  # Use the shared MCP instance
from . import graph, auth
from .context import MicrosoftContext


@mcp.tool()
def list_events(
    ctx: Context,
    account_email: str,
    days_ahead: int = 7,
    days_back: int = 0,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
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
    events = list(
        graph.request_paginated(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "/me/calendarView",
            account_id,
            params=params,
        )
    )

    return events


@mcp.tool()
def get_event(ctx: Context, event_id: str, account_email: str) -> dict[str, Any]:
    """Get a single calendar event by ID"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)

    result = graph.request(
        context.http_client, context.cache_file, context.scopes, context.settings, context.base_url, "GET", f"/me/events/{event_id}", account_id
    )
    if not result:
        raise ValueError(f"Event '{event_id}' not found")
    return result


@mcp.tool()
def create_event(
    ctx: Context,
    account_email: str,
    subject: str,
    start: str,
    end: str,
    location: str | None = None,
    body: str | None = None,
    attendees: list[str] | None = None,
    timezone: str = "UTC",
) -> dict[str, Any]:
    """start/end: ISO-8601 datetime (e.g. '2024-01-15T14:00:00'). attendees: list of email addresses"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
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

    result = graph.request(
        context.http_client,
        context.cache_file,
        context.scopes,
        context.settings,
        context.base_url,
        "POST",
        "/me/events",
        account_id,
        json=event,
    )
    if not result:
        raise ValueError("Failed to create event")
    return result


@mcp.tool()
def update_event(ctx: Context, event_id: str, updates: dict[str, Any], account_email: str) -> dict[str, Any]:
    """updates keys: 'subject', 'start' (ISO-8601), 'end' (ISO-8601), 'location', 'body', 'timezone'"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
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
        context.http_client,
        context.cache_file,
        context.scopes,
        context.settings,
        context.base_url,
        "PATCH",
        f"/me/events/{event_id}",
        account_id,
        json=formatted_updates,
    )
    return result or {"status": "updated"}


@mcp.tool()
def delete_event(ctx: Context, account_email: str, event_id: str, send_cancellation: bool = True) -> dict[str, str]:
    """Delete or cancel a calendar event"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)

    if send_cancellation:
        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "POST",
            f"/me/events/{event_id}/cancel",
            account_id,
            json={},
        )
    else:
        graph.request(
            context.http_client,
            context.cache_file,
            context.scopes,
            context.settings,
            context.base_url,
            "DELETE",
            f"/me/events/{event_id}",
            account_id,
        )
    return {"status": "deleted", "event_id": event_id}


@mcp.tool()
def respond_event(
    ctx: Context,
    account_email: str,
    event_id: str,
    response: Literal["accept", "decline", "tentativelyAccept"] = "accept",
    message: str | None = None,
) -> dict[str, str]:
    """Respond to event invitation"""
    context: MicrosoftContext = ctx.request_context.lifespan_context
    account_id = auth.get_account_id_by_email(account_email, context.cache_file, settings=context.settings)
    payload: dict[str, Any] = {"sendResponse": True}
    if message:
        payload["comment"] = message

    graph.request(
        context.http_client,
        context.cache_file,
        context.scopes,
        context.settings,
        context.base_url,
        "POST",
        f"/me/events/{event_id}/{response}",
        account_id,
        json=payload,
    )
    return {"status": response}
