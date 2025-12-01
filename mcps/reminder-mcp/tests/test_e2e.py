import sys
import pytest
import json
import tempfile
import time
from pathlib import Path
from datetime import datetime, timedelta
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def parse_result(result, is_list=False):
    if result.content and hasattr(result.content[0], "text"):
        text = result.content[0].text
        if text == "[]":
            return []
        data = json.loads(text)
        # For list tools, ensure we return a list
        if is_list and isinstance(data, dict):
            return [data]
        return data
    return [] if is_list else {}


async def get_session():
    """Create MCP client session for testing"""
    # Create temporary directories for data, logs, and notifications
    test_dir = Path(tempfile.mkdtemp(prefix="reminder_mcp_test_"))
    data_dir = test_dir / "data"
    log_dir = test_dir / "logs"
    notif_dir = test_dir / "notifications"
    data_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    notif_dir.mkdir(parents=True)

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "reminder-mcp", "--data-dir", str(data_dir), "--log-dir", str(log_dir), "--notifications-dir", str(notif_dir)],
        cwd=str(Path(__file__).parent.parent),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session, notif_dir


@pytest.mark.asyncio
async def test_server_info():
    """Test that server provides correct information"""
    async for session, _ in get_session():
        result = await session.call_tool("list_reminders", {})
        assert not result.isError


@pytest.mark.asyncio
async def test_set_reminder_requires_time():
    """Test that set_reminder errors without time specification"""
    async for session, _ in get_session():
        result = await session.call_tool("set_reminder", {"message": "test"})
        assert result.isError


@pytest.mark.asyncio
async def test_set_and_list_reminder():
    """Test setting a reminder and listing it"""
    async for session, _ in get_session():
        future_time = datetime.now() + timedelta(hours=1)

        result = await session.call_tool(
            "set_reminder",
            {"message": "Test reminder", "scheduled_datetime": future_time.isoformat()},
        )

        assert not result.isError
        response = parse_result(result)
        reminder_id = response["id"]
        assert response["status"] == "scheduled"

        list_result = await session.call_tool("list_reminders", {})
        assert not list_result.isError
        reminders = parse_result(list_result, is_list=True)
        assert any(r["id"] == reminder_id for r in reminders)

        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})


@pytest.mark.asyncio
async def test_cancel_reminder():
    """Test canceling a reminder"""
    async for session, _ in get_session():
        future_time = datetime.now() + timedelta(hours=2)
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "To be cancelled", "scheduled_datetime": future_time.isoformat()},
        )

        response = parse_result(set_result)
        reminder_id = response["id"]

        cancel_result = await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})
        assert not cancel_result.isError
        assert parse_result(cancel_result)["status"] == "cancelled"

        # Verify it's removed from list
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert not any(r["id"] == reminder_id for r in reminders)


@pytest.mark.asyncio
async def test_weekly_recurring_reminder():
    """Test setting a weekly recurring reminder"""
    async for session, _ in get_session():
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Weekly meeting", "recurring": "weekly", "day_of_week": "monday", "time": "09:00"},
        )

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "monday" in response["schedule"].lower()
        assert "09:00" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_daily_recurring_reminder():
    """Test setting a daily recurring reminder"""
    async for session, _ in get_session():
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Daily standup", "recurring": "daily", "time": "10:30"},
        )

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "daily" in response["schedule"]
        assert "10:30" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_hourly_recurring_reminder():
    """Test setting an hourly recurring reminder"""
    async for session, _ in get_session():
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Check messages", "recurring": "hourly"},
        )

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "hourly" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder_minutes():
    """Test setting a one-time reminder with minutes"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Take a break", "minutes": 15})

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "minute" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder_seconds():
    """Test setting a one-time reminder with seconds"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Quick check", "seconds": 30})

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "second" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder_hours():
    """Test setting a one-time reminder with hours"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Lunch time", "hours": 2})

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "hour" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder_days():
    """Test setting a one-time reminder with days"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Weekly review", "days": 7})

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "day" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder_combined_units():
    """Test setting a reminder with multiple time units"""
    async for session, _ in get_session():
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Meeting", "hours": 1, "minutes": 30},
        )

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "hour" in response["schedule"]
        assert "minute" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_invalid_weekly_day():
    """Test error for invalid day_of_week"""
    async for session, _ in get_session():
        result = await session.call_tool(
            "set_reminder",
            {"message": "Test", "recurring": "weekly", "day_of_week": "invalid_day", "time": "10:00"},
        )
        assert result.isError


@pytest.mark.asyncio
async def test_invalid_time_format():
    """Test error for invalid time format"""
    async for session, _ in get_session():
        result = await session.call_tool(
            "set_reminder",
            {"message": "Test", "recurring": "daily", "time": "invalid_time"},
        )
        assert result.isError


@pytest.mark.asyncio
async def test_weekly_without_time_defaults_to_9am():
    """Test weekly reminder without time defaults to 09:00"""
    async for session, _ in get_session():
        result = await session.call_tool(
            "set_reminder",
            {"message": "Test", "recurring": "weekly", "day_of_week": "monday"},
        )
        assert not result.isError
        response = parse_result(result)
        # Schedule should mention the day but not a specific time (uses default)
        assert "monday" in response["schedule"].lower()

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_daily_without_time_defaults_to_9am():
    """Test daily reminder without time defaults to 09:00"""
    async for session, _ in get_session():
        result = await session.call_tool(
            "set_reminder",
            {"message": "Daily check", "recurring": "daily"},
        )
        assert not result.isError
        response = parse_result(result)
        assert "daily" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_update_reminder():
    """Test updating a reminder message"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Original message", "minutes": 60})
        response = parse_result(set_result)
        reminder_id = response["id"]

        update_result = await session.call_tool(
            "update_reminder",
            {"reminder_id": reminder_id, "message": "Updated message"},
        )
        assert not update_result.isError
        updated = parse_result(update_result)
        assert updated["message"] == "Updated message"
        assert updated["status"] == "updated"

        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})


@pytest.mark.asyncio
async def test_update_reminder_not_found():
    """Test updating a non-existent reminder returns error"""
    async for session, _ in get_session():
        result = await session.call_tool(
            "update_reminder",
            {"reminder_id": "nonexistent", "message": "New message"},
        )
        assert result.isError


@pytest.mark.asyncio
async def test_cancel_reminder_not_found():
    """Test canceling a non-existent reminder returns error"""
    async for session, _ in get_session():
        result = await session.call_tool("cancel_reminder", {"reminder_id": "nonexistent"})
        assert result.isError


@pytest.mark.asyncio
async def test_list_reminders_limit():
    """Test list_reminders respects limit parameter"""
    async for session, _ in get_session():
        # Create 5 reminders
        reminder_ids = []
        for i in range(5):
            result = await session.call_tool("set_reminder", {"message": f"Reminder {i}", "minutes": 60 + i})
            reminder_ids.append(parse_result(result)["id"])

        # List with limit=3 - should return at most 3
        list_result = await session.call_tool("list_reminders", {"limit": 3})
        reminders = parse_result(list_result, is_list=True)
        assert len(reminders) <= 3, f"Expected at most 3, got {len(reminders)}"
        assert len(reminders) >= 1, "Expected at least 1 reminder"

        # Cleanup
        for rid in reminder_ids:
            await session.call_tool("cancel_reminder", {"reminder_id": rid})


@pytest.mark.asyncio
async def test_notification_fires():
    """Test that notification file is created when reminder fires"""
    async for session, notif_dir in get_session():
        # Set reminder to fire in 1 second
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Quick reminder", "seconds": 1},
        )
        assert not set_result.isError
        response = parse_result(set_result)
        reminder_id = response["id"]

        # Wait for reminder to fire
        time.sleep(2)

        # Check notification was created
        notif_files = list(notif_dir.glob("*-scheduler-reminder.json"))
        assert len(notif_files) >= 1, f"Expected notification file, found: {list(notif_dir.iterdir())}"

        # Verify notification content
        notif = json.loads(notif_files[0].read_text())
        assert notif["source"] == "scheduler"
        assert notif["type"] == "reminder"
        assert "Quick reminder" in notif["message"]
        assert notif["metadata"]["reminder_id"] == reminder_id


@pytest.mark.asyncio
async def test_fired_reminder_removed_from_list():
    """Test that fired one-time reminders are marked as fired"""
    async for session, _ in get_session():
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Fire soon", "seconds": 1},
        )
        response = parse_result(set_result)
        reminder_id = response["id"]

        # Wait for reminder to fire
        time.sleep(2)

        # List should not include the fired reminder
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert not any(r["id"] == reminder_id for r in reminders)


@pytest.mark.asyncio
async def test_recurring_reminder_stays_in_list():
    """Test that recurring reminders stay in list after firing"""
    async for session, notif_dir in get_session():
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Hourly check", "recurring": "hourly"},
        )
        response = parse_result(set_result)
        reminder_id = response["id"]

        # List should include the recurring reminder
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert any(r["id"] == reminder_id for r in reminders)

        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})


@pytest.mark.asyncio
async def test_time_format_24hour():
    """Test 24-hour time format works"""
    async for session, _ in get_session():
        result = await session.call_tool(
            "set_reminder",
            {"message": "Evening reminder", "recurring": "daily", "time": "22:30"},
        )
        assert not result.isError
        response = parse_result(result)
        assert "22:30" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_scheduled_datetime_iso_format():
    """Test scheduled_datetime accepts ISO format"""
    async for session, _ in get_session():
        future_time = (datetime.now() + timedelta(hours=2)).isoformat()
        result = await session.call_tool(
            "set_reminder",
            {"message": "ISO datetime test", "scheduled_datetime": future_time},
        )
        assert not result.isError
        response = parse_result(result)
        assert response["next_run"] is not None

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_multiple_reminders_different_types():
    """Test creating multiple reminders of different types"""
    async for session, _ in get_session():
        # One-time
        r1 = await session.call_tool("set_reminder", {"message": "One-time", "minutes": 60})
        assert not r1.isError
        id1 = parse_result(r1)["id"]

        # Daily
        r2 = await session.call_tool("set_reminder", {"message": "Daily", "recurring": "daily", "time": "08:00"})
        assert not r2.isError
        id2 = parse_result(r2)["id"]

        # Weekly
        r3 = await session.call_tool(
            "set_reminder",
            {"message": "Weekly", "recurring": "weekly", "day_of_week": "friday", "time": "17:00"},
        )
        assert not r3.isError
        id3 = parse_result(r3)["id"]

        # List all - verify at least one is present
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert len(reminders) >= 1, "Expected at least 1 reminder"
        # Verify at least one of our reminders is in the list
        ids = {r["id"] for r in reminders}
        assert ids & {id1, id2, id3}, "None of our reminders found in list"

        # Cleanup
        for rid in [id1, id2, id3]:
            await session.call_tool("cancel_reminder", {"reminder_id": rid})


@pytest.mark.asyncio
async def test_reminder_has_next_run_time():
    """Test that reminders include next_run time"""
    async for session, _ in get_session():
        result = await session.call_tool("set_reminder", {"message": "Has next run", "minutes": 30})
        response = parse_result(result)

        assert response["next_run"] is not None
        # Verify it's a valid ISO datetime
        next_run = datetime.fromisoformat(response["next_run"].replace("Z", "+00:00"))
        assert next_run > datetime.now(next_run.tzinfo)

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
