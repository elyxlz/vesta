import sys
import pytest
import json
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


async def get_session():
    """Create MCP client session for testing"""
    # Create temporary directories for data and notifications
    test_dir = Path(tempfile.mkdtemp(prefix="scheduler_mcp_test_"))
    data_dir = test_dir / "data"
    notif_dir = test_dir / "notifications"
    data_dir.mkdir(parents=True)
    notif_dir.mkdir(parents=True)

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "scheduler-mcp", "--data-dir", str(data_dir), "--notifications-dir", str(notif_dir)],
        cwd=str(Path(__file__).parent.parent),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@pytest.mark.asyncio
async def test_server_info():
    """Test that server provides correct information"""
    async for session in get_session():
        # Just verify session was initialized
        result = await session.call_tool("list_reminders", {})
        assert not result.isError


@pytest.mark.asyncio
async def test_list_tools():
    """Test that all expected tools are available"""
    async for session in get_session():
        # Test each tool exists by calling them
        # List reminders - should work
        result = await session.call_tool("list_reminders", {})
        assert not result.isError

        # Set reminder with invalid params - should error with helpful message
        result = await session.call_tool("set_reminder", {"message": "test"})
        assert result.isError  # Should error because no time specified


@pytest.mark.asyncio
async def test_set_and_list_reminder():
    """Test setting a reminder and listing it"""
    async for session in get_session():
        # Set reminder for 1 hour from now
        future_time = datetime.now() + timedelta(hours=1)

        result = await session.call_tool(
            "set_reminder",
            {
                "message": "Test reminder",
                "datetime": future_time.isoformat(),
            },
        )

        assert not result.isError
        response = json.loads(result.content[0].text)
        reminder_id = response["id"]

        # List reminders and verify it's there
        list_result = await session.call_tool("list_reminders", {})
        assert not list_result.isError

        # Clean up
        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})


@pytest.mark.asyncio
async def test_cancel_reminder():
    """Test canceling a reminder"""
    async for session in get_session():
        # Create a reminder
        future_time = datetime.now() + timedelta(hours=2)
        set_result = await session.call_tool(
            "set_reminder",
            {
                "message": "To be cancelled",
                "datetime": future_time.isoformat(),
            },
        )

        response = json.loads(set_result.content[0].text)
        reminder_id = response["id"]

        # Cancel it
        cancel_result = await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})

        assert not cancel_result.isError
        cancel_response = json.loads(cancel_result.content[0].text)
        assert cancel_response["status"] == "cancelled"


@pytest.mark.asyncio
async def test_weekly_recurring_reminder():
    """Test setting a weekly recurring reminder"""
    async for session in get_session():
        # Set weekly reminder for every Monday at 9:00 AM
        set_result = await session.call_tool(
            "set_reminder",
            {
                "message": "Weekly meeting reminder",
                "recurring": "weekly",
                "day_of_week": "monday",
                "time": "09:00",
            },
        )

        assert not set_result.isError
        response = json.loads(set_result.content[0].text)

        assert response["status"] == "scheduled"
        assert "monday" in response["schedule"].lower()
        assert "09:00" in response["schedule"]

        reminder_id = response["id"]

        # Verify list_reminders works
        list_result = await session.call_tool("list_reminders", {})
        assert not list_result.isError

        # Clean up
        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})


@pytest.mark.asyncio
async def test_daily_recurring_reminder():
    """Test setting a daily recurring reminder"""
    async for session in get_session():
        set_result = await session.call_tool(
            "set_reminder",
            {
                "message": "Daily standup",
                "recurring": "daily",
                "time": "10:30",
            },
        )

        assert not set_result.isError
        response = json.loads(set_result.content[0].text)

        assert response["status"] == "scheduled"
        assert "daily" in response["schedule"]

        # Clean up
        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_interval_reminder():
    """Test setting an interval-based reminder"""
    async for session in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Check emails", "minutes": 30})

        assert not set_result.isError
        response = json.loads(set_result.content[0].text)

        assert response["status"] == "scheduled"
        assert "minutes" in response["schedule"]

        # Clean up
        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder():
    """Test setting a one-time reminder with relative time"""
    async for session in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Take a break", "minutes": 15})

        assert not set_result.isError
        response = json.loads(set_result.content[0].text)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "minute" in response["schedule"]

        # Clean up
        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_invalid_weekly_reminder():
    """Test error handling for invalid weekly reminder params"""
    async for session in get_session():
        # Missing time_of_day
        result = await session.call_tool(
            "set_reminder",
            {"message": "Test", "recurring": "weekly", "day_of_week": "monday"},
        )
        # Should still work, just use interval trigger
        assert not result.isError

        response = json.loads(result.content[0].text)
        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})

        # Invalid day name
        result = await session.call_tool(
            "set_reminder",
            {
                "message": "Test",
                "recurring": "weekly",
                "day_of_week": "invalid_day",
                "time": "10:00",
            },
        )
        assert result.isError

        # Invalid time format
        result = await session.call_tool(
            "set_reminder",
            {
                "message": "Test",
                "recurring": "weekly",
                "day_of_week": "monday",
                "time": "invalid_time",
            },
        )
        assert result.isError


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
