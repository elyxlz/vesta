import os
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest
from dotenv import load_dotenv, find_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv(find_dotenv())

if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
    pytest.fail("MICROSOFT_MCP_CLIENT_ID environment variable is required")


def parse_result(result, tool_name: str | None = None):
    """Helper to parse MCP tool results consistently."""
    if result.content and hasattr(result.content[0], "text"):
        text = result.content[0].text
        if text == "[]":
            return []
        data = json.loads(text)
        list_tools = {"list_accounts", "list_emails", "list_events", "list_calendars", "search_emails"}
        if tool_name in list_tools and isinstance(data, dict):
            return [data]
        return data
    return []


async def get_session():
    """Yield an initialized MCP session backed by local data dir (for auth) and temp dirs for logs/notifications."""
    # Use local data dir for auth cache, temp dirs for logs/notifications
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(tempfile.mkdtemp(prefix="microsoft_mcp_test_logs_"))
    notif_dir = Path(tempfile.mkdtemp(prefix="microsoft_mcp_test_notif_"))

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "microsoft-mcp", "--data-dir", str(data_dir), "--log-dir", str(log_dir), "--notifications-dir", str(notif_dir)],
        env={
            "MICROSOFT_MCP_CLIENT_ID": os.getenv("MICROSOFT_MCP_CLIENT_ID", ""),
            "MICROSOFT_MCP_TENANT_ID": os.getenv("MICROSOFT_MCP_TENANT_ID", "common"),
        },
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def get_account_context(session):
    """Return the first available account context (email + ID)."""
    result = await session.call_tool("list_accounts", {})
    assert not result.isError
    accounts = parse_result(result, "list_accounts")
    assert accounts, "No accounts found - authenticate first"
    return {"email": accounts[0]["email"], "account_id": accounts[0]["account_id"]}


@pytest.mark.asyncio
async def test_list_accounts():
    async for session in get_session():
        result = await session.call_tool("list_accounts", {})
        assert not result.isError
        accounts = parse_result(result, "list_accounts")
        assert accounts
        assert "email" in accounts[0]
        assert "account_id" in accounts[0]


@pytest.mark.asyncio
async def test_list_emails_metadata_only():
    async for session in get_session():
        account = await get_account_context(session)
        result = await session.call_tool("list_emails", {"account_email": account["email"], "limit": 3})
        assert not result.isError
        emails = parse_result(result, "list_emails")
        if emails:
            assert "body" not in emails[0]
            assert "preview" in emails[0]


@pytest.mark.asyncio
async def test_get_email():
    async for session in get_session():
        account = await get_account_context(session)
        list_result = await session.call_tool("list_emails", {"account_email": account["email"], "limit": 1})
        emails = parse_result(list_result, "list_emails")
        if not emails:
            pytest.skip("No emails available to fetch")

        email_id = emails[0]["id"]
        result = await session.call_tool("get_email", {"account_email": account["email"], "email_id": email_id})
        assert not result.isError
        email_detail = parse_result(result)
        assert email_detail.get("id") == email_id
        assert "body" not in email_detail
        assert "body_saved_to" in email_detail
        assert email_detail.get("body_length", 0) >= 0


@pytest.mark.asyncio
async def test_create_email_draft():
    async for session in get_session():
        account = await get_account_context(session)
        result = await session.call_tool(
            "create_email_draft",
            {
                "account_email": account["email"],
                "to": [account["email"]],
                "subject": "MCP Test Draft",
                "body": "This is a test draft email",
            },
        )
        assert not result.isError
        draft = parse_result(result)
        assert draft and "id" in draft


@pytest.mark.asyncio
async def test_update_email_toggle_read_state():
    async for session in get_session():
        account = await get_account_context(session)
        list_result = await session.call_tool("list_emails", {"account_email": account["email"], "limit": 1})
        emails = parse_result(list_result, "list_emails")
        if not emails:
            pytest.skip("No emails available to update")

        email = emails[0]
        email_id = email["id"]
        original_state = email.get("isRead", True)

        toggle_result = await session.call_tool(
            "update_email",
            {"account_email": account["email"], "email_id": email_id, "is_read": not original_state},
        )
        assert not toggle_result.isError

        restore_result = await session.call_tool(
            "update_email",
            {"account_email": account["email"], "email_id": email_id, "is_read": original_state},
        )
        assert not restore_result.isError


@pytest.mark.asyncio
async def test_send_email():
    async for session in get_session():
        account = await get_account_context(session)
        result = await session.call_tool(
            "send_email",
            {
                "account_email": account["email"],
                "to": [account["email"]],
                "subject": f"MCP Test Send Email {datetime.now(timezone.utc).isoformat()}",
                "body": "This is a test email sent via send_email tool",
            },
        )
        assert not result.isError
        sent = parse_result(result)
        assert sent and sent.get("status") == "sent"


@pytest.mark.asyncio
async def test_reply_to_email_with_reply_all_flag():
    async for session in get_session():
        account = await get_account_context(session)
        list_result = await session.call_tool("list_emails", {"account_email": account["email"], "limit": 5})
        emails = parse_result(list_result, "list_emails")
        if not emails:
            pytest.skip("No emails available to reply to")

        target = next((email for email in emails if email.get("conversationId")), emails[0])
        result = await session.call_tool(
            "reply_to_email",
            {
                "account_email": account["email"],
                "email_id": target["id"],
                "body": "Automated integration-test reply.",
                "reply_all": True,
            },
        )
        assert not result.isError
        reply = parse_result(result)
        assert reply and reply.get("status") == "sent"


@pytest.mark.asyncio
async def test_get_attachment_from_draft():
    async for session in get_session():
        account = await get_account_context(session)
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as tmp_file:
            tmp_file.write("This is a test attachment content")
            attachment_path = tmp_file.name

        try:
            draft_result = await session.call_tool(
                "create_email_draft",
                {
                    "account_email": account["email"],
                    "to": [account["email"]],
                    "subject": "MCP Test Email with Attachment",
                    "body": "This email contains a test attachment",
                    "attachments": [attachment_path],
                },
            )
            assert not draft_result.isError
            draft = parse_result(draft_result)
            email_id = draft["id"]

            email_result = await session.call_tool("get_email", {"account_email": account["email"], "email_id": email_id})
            email_detail = parse_result(email_result)
            attachments = email_detail.get("attachments", [])
            if not attachments:
                pytest.skip("Email draft did not return attachments")

            attachment = attachments[0]
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as save_file:
                save_path = save_file.name

            try:
                result = await session.call_tool(
                    "get_attachment",
                    {
                        "account_email": account["email"],
                        "email_id": email_id,
                        "attachment_id": attachment["id"],
                        "save_path": save_path,
                    },
                )
                assert not result.isError
                attachment_data = parse_result(result)
                assert attachment_data and attachment_data["saved_to"] == save_path
                with open(save_path) as f:
                    assert f.read() == "This is a test attachment content"
            finally:
                if os.path.exists(save_path):
                    os.unlink(save_path)
        finally:
            if os.path.exists(attachment_path):
                os.unlink(attachment_path)


@pytest.mark.asyncio
async def test_search_emails_metadata_only():
    async for session in get_session():
        account = await get_account_context(session)
        result = await session.call_tool("search_emails", {"account_email": account["email"], "query": "test", "limit": 5})
        assert not result.isError
        results = parse_result(result, "search_emails")
        assert isinstance(results, list)
        if results:
            assert "body" not in results[0]


@pytest.mark.asyncio
async def test_list_events():
    async for session in get_session():
        account = await get_account_context(session)
        result = await session.call_tool("list_events", {"account_email": account["email"], "days_ahead": 3})
        assert not result.isError
        events = parse_result(result, "list_events")
        assert isinstance(events, list)


@pytest.mark.asyncio
async def test_calendar_crud_flow():
    async for session in get_session():
        account = await get_account_context(session)
        start_time = datetime.now(timezone.utc) + timedelta(days=5)
        end_time = start_time + timedelta(hours=1)

        create_result = await session.call_tool(
            "create_event",
            {
                "account_email": account["email"],
                "subject": "MCP Test Event",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "body": "Integration test event",
                "attendees": [account["email"]],
            },
        )
        assert not create_result.isError
        event = parse_result(create_result)
        event_id = event["id"]

        get_result = await session.call_tool("get_event", {"account_email": account["email"], "event_id": event_id})
        assert not get_result.isError
        fetched = parse_result(get_result)
        assert fetched.get("id") == event_id

        new_start = start_time + timedelta(hours=2)
        new_end = new_start + timedelta(hours=1)
        update_result = await session.call_tool(
            "update_event",
            {
                "account_email": account["email"],
                "event_id": event_id,
                "updates": {"subject": "MCP Test Event (Updated)", "start": new_start.isoformat(), "end": new_end.isoformat()},
            },
        )
        assert not update_result.isError

        delete_result = await session.call_tool(
            "delete_event",
            {"account_email": account["email"], "event_id": event_id, "send_cancellation": False},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_respond_event_if_invite_available():
    async for session in get_session():
        account = await get_account_context(session)
        list_result = await session.call_tool("list_events", {"account_email": account["email"], "days_ahead": 30})
        events = parse_result(list_result, "list_events")
        if not events:
            pytest.skip("No events available to respond to")

        invite_event = next((e for e in events if e.get("attendees")), None)
        if not invite_event:
            pytest.skip("No events with attendees to respond to")

        result = await session.call_tool(
            "respond_event",
            {
                "account_email": account["email"],
                "event_id": invite_event["id"],
                "response": "tentativelyAccept",
                "message": "Automated tentative response",
            },
        )
        assert not result.isError
        response = parse_result(result)
        assert response and response.get("status") == "tentativelyAccept"


@pytest.mark.asyncio
async def test_list_calendars():
    async for session in get_session():
        account = await get_account_context(session)
        result = await session.call_tool("list_calendars", {"account_email": account["email"]})
        assert not result.isError
        calendars = parse_result(result, "list_calendars")
        assert isinstance(calendars, list)
        assert len(calendars) > 0
        # Should have at least the default calendar
        assert any(c.get("isDefaultCalendar") for c in calendars)
        # Each calendar should have id and name
        for cal in calendars:
            assert "id" in cal
            assert "name" in cal


@pytest.mark.asyncio
async def test_create_all_day_event():
    async for session in get_session():
        account = await get_account_context(session)
        event_date = (datetime.now(timezone.utc) + timedelta(days=10)).strftime("%Y-%m-%d")

        create_result = await session.call_tool(
            "create_event",
            {
                "account_email": account["email"],
                "subject": "MCP Test All-Day Event",
                "start": event_date,
                "is_all_day": True,
                "body": "Integration test all-day event",
            },
        )
        assert not create_result.isError
        event = parse_result(create_result)
        event_id = event["id"]
        assert event.get("isAllDay") is True

        # Cleanup
        delete_result = await session.call_tool(
            "delete_event",
            {"account_email": account["email"], "event_id": event_id, "send_cancellation": False},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_create_yearly_recurring_event():
    async for session in get_session():
        account = await get_account_context(session)
        event_date = (datetime.now(timezone.utc) + timedelta(days=15)).strftime("%Y-%m-%d")

        create_result = await session.call_tool(
            "create_event",
            {
                "account_email": account["email"],
                "subject": "MCP Test Birthday (Yearly)",
                "start": event_date,
                "is_all_day": True,
                "recurrence": "yearly",
                "body": "Integration test yearly recurring event",
            },
        )
        assert not create_result.isError
        event = parse_result(create_result)
        event_id = event["id"]
        assert event.get("recurrence") is not None
        assert event["recurrence"]["pattern"]["type"] == "absoluteYearly"

        # Cleanup - delete the series master
        delete_result = await session.call_tool(
            "delete_event",
            {"account_email": account["email"], "event_id": event_id, "send_cancellation": False},
        )
        assert not delete_result.isError


@pytest.mark.asyncio
async def test_create_event_on_specific_calendar():
    async for session in get_session():
        account = await get_account_context(session)

        start_time = datetime.now(timezone.utc) + timedelta(days=7)
        end_time = start_time + timedelta(hours=1)

        # Use calendar_name instead of calendar_id - uses default "Calendar"
        create_result = await session.call_tool(
            "create_event",
            {
                "account_email": account["email"],
                "subject": "MCP Test Event on Specific Calendar",
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "calendar_name": "Calendar",
                "body": "Integration test event on specific calendar",
            },
        )
        assert not create_result.isError
        event = parse_result(create_result)
        event_id = event["id"]

        # Cleanup
        delete_result = await session.call_tool(
            "delete_event",
            {"account_email": account["email"], "event_id": event_id, "send_cancellation": False},
        )
        assert not delete_result.isError
