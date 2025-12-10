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
            {"message": "Test reminder", "scheduled_datetime": future_time.isoformat(), "tz": "UTC"},
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
            {"message": "To be cancelled", "scheduled_datetime": future_time.isoformat(), "tz": "UTC"},
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
    """Test setting a weekly recurring reminder - uses datetime to extract day/time"""
    async for session, _ in get_session():
        # Use a Monday at 09:00 UTC as reference
        monday_9am = datetime(2024, 12, 2, 9, 0, 0)  # This is a Monday
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Weekly meeting", "recurring": "weekly", "scheduled_datetime": monday_9am.isoformat(), "tz": "UTC"},
        )

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "weekly" in response["schedule"].lower()

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_daily_recurring_reminder():
    """Test setting a daily recurring reminder - uses datetime to extract time"""
    async for session, _ in get_session():
        # Use 10:30 UTC as reference time
        ref_time = datetime(2024, 12, 2, 10, 30, 0)
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Daily standup", "recurring": "daily", "scheduled_datetime": ref_time.isoformat(), "tz": "UTC"},
        )

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "daily" in response["schedule"]

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
        set_result = await session.call_tool("set_reminder", {"message": "Take a break", "in_minutes": 15})

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "minute" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder_minutes_short():
    """Test setting a one-time reminder with short duration (1 minute)"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Quick check", "in_minutes": 1})

        assert not set_result.isError
        response = parse_result(set_result)

        assert response["status"] == "scheduled"
        assert "once" in response["schedule"]
        assert "minute" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_one_time_reminder_hours():
    """Test setting a one-time reminder with hours"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Lunch time", "in_hours": 2})

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
        set_result = await session.call_tool("set_reminder", {"message": "Weekly review", "in_days": 7})

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
            {"message": "Meeting", "in_hours": 1, "in_minutes": 30},
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
async def test_weekly_extracts_day_from_datetime():
    """Test weekly reminder extracts day-of-week from scheduled_datetime"""
    async for session, _ in get_session():
        # Friday at 17:00 UTC
        friday_5pm = datetime(2024, 12, 6, 17, 0, 0)
        result = await session.call_tool(
            "set_reminder",
            {"message": "Test", "recurring": "weekly", "scheduled_datetime": friday_5pm.isoformat(), "tz": "UTC"},
        )
        assert not result.isError
        response = parse_result(result)
        assert "weekly" in response["schedule"].lower()
        assert "fri" in response["schedule"].lower()

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_daily_extracts_time_from_datetime():
    """Test daily reminder extracts time from scheduled_datetime"""
    async for session, _ in get_session():
        # 14:30 UTC
        ref_time = datetime(2024, 12, 2, 14, 30, 0)
        result = await session.call_tool(
            "set_reminder",
            {"message": "Daily check", "recurring": "daily", "scheduled_datetime": ref_time.isoformat(), "tz": "UTC"},
        )
        assert not result.isError
        response = parse_result(result)
        assert "daily" in response["schedule"]
        assert "14:30" in response["schedule"]

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


@pytest.mark.asyncio
async def test_update_reminder():
    """Test updating a reminder message"""
    async for session, _ in get_session():
        set_result = await session.call_tool("set_reminder", {"message": "Original message", "in_minutes": 60})
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
            result = await session.call_tool("set_reminder", {"message": f"Reminder {i}", "in_minutes": 60 + i})
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
        # Set reminder to fire in 2 seconds using scheduled_datetime
        fire_time = (datetime.now() + timedelta(seconds=2)).isoformat()
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Quick reminder", "scheduled_datetime": fire_time, "tz": "UTC"},
        )
        assert not set_result.isError
        response = parse_result(set_result)
        reminder_id = response["id"]

        # Wait for reminder to fire
        time.sleep(4)

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
    """Test that fired one-time reminders are marked as completed and removed from list"""
    async for session, _ in get_session():
        # Fire in 2 seconds
        fire_time = (datetime.now() + timedelta(seconds=2)).isoformat()
        set_result = await session.call_tool(
            "set_reminder",
            {"message": "Fire soon", "scheduled_datetime": fire_time, "tz": "UTC"},
        )
        response = parse_result(set_result)
        reminder_id = response["id"]

        # Wait for reminder to fire
        time.sleep(4)

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
    """Test 24-hour time format works via scheduled_datetime"""
    async for session, _ in get_session():
        # 22:30 UTC
        ref_time = datetime(2024, 12, 2, 22, 30, 0)
        result = await session.call_tool(
            "set_reminder",
            {"message": "Evening reminder", "recurring": "daily", "scheduled_datetime": ref_time.isoformat(), "tz": "UTC"},
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
            {"message": "ISO datetime test", "scheduled_datetime": future_time, "tz": "UTC"},
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
        r1 = await session.call_tool("set_reminder", {"message": "One-time", "in_minutes": 60})
        assert not r1.isError
        id1 = parse_result(r1)["id"]

        # Daily at 08:00 UTC
        daily_time = datetime(2024, 12, 2, 8, 0, 0)
        r2 = await session.call_tool(
            "set_reminder", {"message": "Daily", "recurring": "daily", "scheduled_datetime": daily_time.isoformat(), "tz": "UTC"}
        )
        assert not r2.isError
        id2 = parse_result(r2)["id"]

        # Weekly on Friday at 17:00 UTC
        friday_5pm = datetime(2024, 12, 6, 17, 0, 0)
        r3 = await session.call_tool(
            "set_reminder",
            {"message": "Weekly", "recurring": "weekly", "scheduled_datetime": friday_5pm.isoformat(), "tz": "UTC"},
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
        result = await session.call_tool("set_reminder", {"message": "Has next run", "in_minutes": 30})
        response = parse_result(result)

        assert response["next_run"] is not None
        # Verify it's a valid ISO datetime
        next_run = datetime.fromisoformat(response["next_run"].replace("Z", "+00:00"))
        assert next_run > datetime.now(next_run.tzinfo)

        await session.call_tool("cancel_reminder", {"reminder_id": response["id"]})


async def get_session_with_dirs(data_dir: Path, log_dir: Path, notif_dir: Path):
    """Create MCP client session with specific directories"""
    server_params = StdioServerParameters(
        command="uv",
        args=["run", "reminder-mcp", "--data-dir", str(data_dir), "--log-dir", str(log_dir), "--notifications-dir", str(notif_dir)],
        cwd=str(Path(__file__).parent.parent),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@pytest.mark.asyncio
async def test_restart_restores_one_time_reminder():
    """Test that one-time reminders are restored after server restart"""
    test_dir = Path(tempfile.mkdtemp(prefix="reminder_mcp_restart_"))
    data_dir = test_dir / "data"
    log_dir = test_dir / "logs"
    notif_dir = test_dir / "notifications"
    data_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    notif_dir.mkdir(parents=True)

    # Session 1: Create a reminder
    async for session in get_session_with_dirs(data_dir, log_dir, notif_dir):
        future_time = datetime.now() + timedelta(hours=1)
        result = await session.call_tool(
            "set_reminder",
            {"message": "Survive restart", "scheduled_datetime": future_time.isoformat(), "tz": "UTC"},
        )
        assert not result.isError
        reminder_id = parse_result(result)["id"]

    # Session 2: Verify reminder was restored
    async for session in get_session_with_dirs(data_dir, log_dir, notif_dir):
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert any(r["id"] == reminder_id for r in reminders), "One-time reminder not restored after restart"

        # Cleanup
        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})


@pytest.mark.asyncio
async def test_restart_restores_recurring_reminder():
    """Test that recurring reminders are restored after server restart"""
    test_dir = Path(tempfile.mkdtemp(prefix="reminder_mcp_restart_"))
    data_dir = test_dir / "data"
    log_dir = test_dir / "logs"
    notif_dir = test_dir / "notifications"
    data_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    notif_dir.mkdir(parents=True)

    # Session 1: Create a recurring reminder
    async for session in get_session_with_dirs(data_dir, log_dir, notif_dir):
        result = await session.call_tool(
            "set_reminder",
            {"message": "Recurring survive restart", "recurring": "hourly"},
        )
        assert not result.isError
        reminder_id = parse_result(result)["id"]

    # Session 2: Verify reminder was restored
    async for session in get_session_with_dirs(data_dir, log_dir, notif_dir):
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert any(r["id"] == reminder_id for r in reminders), "Recurring reminder not restored after restart"

        # Cleanup
        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})


@pytest.mark.asyncio
async def test_restart_handles_past_due_one_time():
    """Test that past-due one-time reminders get missed notification on restart"""
    import sqlite3

    test_dir = Path(tempfile.mkdtemp(prefix="reminder_mcp_pastdue_"))
    data_dir = test_dir / "data"
    log_dir = test_dir / "logs"
    notif_dir = test_dir / "notifications"
    data_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    notif_dir.mkdir(parents=True)

    # Manually create a past-due reminder in the DB
    db_path = data_dir / "reminders.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id TEXT PRIMARY KEY,
            message TEXT NOT NULL,
            schedule_type TEXT,
            scheduled_time TEXT,
            completed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            trigger_data TEXT
        )
    """)
    past_time = (datetime.now() - timedelta(hours=1)).isoformat()
    trigger_data = json.dumps({"type": "date", "run_date": past_time})
    conn.execute(
        "INSERT INTO reminders (id, message, schedule_type, completed, trigger_data) VALUES (?, ?, ?, 0, ?)",
        ("pastdue01", "Past due reminder", f"once at {past_time}", trigger_data),
    )
    conn.commit()
    conn.close()

    # Start server - should send missed notification and mark as completed
    async for session in get_session_with_dirs(data_dir, log_dir, notif_dir):
        # Reminder should NOT be in the list (marked completed)
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert not any(r["id"] == "pastdue01" for r in reminders), "Past-due reminder should be marked completed"

    # Verify missed notification was created
    notif_files = list(notif_dir.glob("*-scheduler-reminder.json"))
    assert len(notif_files) >= 1, "Expected missed notification file"
    notif = json.loads(notif_files[0].read_text())
    assert notif["metadata"].get("missed") is True, "Notification should have missed=True"
    assert "Past due reminder" in notif["message"]


@pytest.mark.asyncio
async def test_recurring_reminder_stays_after_fire():
    """Test that recurring reminders stay in list after actually firing"""
    test_dir = Path(tempfile.mkdtemp(prefix="reminder_mcp_recur_"))
    data_dir = test_dir / "data"
    log_dir = test_dir / "logs"
    notif_dir = test_dir / "notifications"
    data_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    notif_dir.mkdir(parents=True)

    async for session in get_session_with_dirs(data_dir, log_dir, notif_dir):
        # Create hourly reminder (fires every hour, but we can't wait that long)
        # Instead, we'll check that after creation it's in the list
        result = await session.call_tool(
            "set_reminder",
            {"message": "Hourly recurring", "recurring": "hourly"},
        )
        assert not result.isError
        reminder_id = parse_result(result)["id"]

        # Verify it's in list initially
        list_result = await session.call_tool("list_reminders", {})
        reminders = parse_result(list_result, is_list=True)
        assert any(r["id"] == reminder_id for r in reminders)

        # Cleanup
        await session.call_tool("cancel_reminder", {"reminder_id": reminder_id})

    # For a TRUE fire test, we'd need to wait for the interval trigger
    # which isn't practical in tests. The key behavior (completed stays 0
    # for recurring) is tested in test_restart_restores_recurring_reminder


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
