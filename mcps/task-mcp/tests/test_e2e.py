import sys
import pytest
import json
import tempfile
import time
from datetime import datetime
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def parse_result(result, is_list_tool=False):
    if result.content and hasattr(result.content[0], "text"):
        text = result.content[0].text
        if text == "[]":
            return []
        data = json.loads(text)
        if is_list_tool and isinstance(data, dict):
            return [data]
        return data
    return []


async def get_session(*, with_notifications: bool = False, monitor_interval: int = 60):
    test_dir = Path(tempfile.mkdtemp(prefix="task_mcp_test_"))
    data_dir = test_dir / "data"
    log_dir = test_dir / "logs"
    notif_dir = test_dir / "notifications"
    data_dir.mkdir(parents=True)
    log_dir.mkdir(parents=True)
    notif_dir.mkdir(parents=True)

    args = ["run", "task-mcp", "--data-dir", str(data_dir), "--log-dir", str(log_dir)]
    if with_notifications:
        args.extend(["--notifications-dir", str(notif_dir), "--monitor-interval", str(monitor_interval)])

    server_params = StdioServerParameters(
        command="uv",
        args=args,
        cwd=str(Path(__file__).parent.parent),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session, notif_dir


@pytest.mark.asyncio
async def test_add_and_list_task():
    async for session, _ in get_session():
        result = await session.call_tool(
            "add_task",
            {"title": "Test task", "priority": 3, "due": "tomorrow"},
        )

        assert not result.isError
        response = parse_result(result)
        task_id = response["id"]
        assert response["title"] == "Test task"
        assert response["priority"] == 3
        assert response["status"] == "pending"

        list_result = await session.call_tool("list_tasks", {})
        assert not list_result.isError
        tasks = parse_result(list_result, is_list_tool=True)
        assert len(tasks) >= 1
        assert any(t["id"] == task_id for t in tasks)


@pytest.mark.asyncio
async def test_update_task():
    async for session, _ in get_session():
        add_result = await session.call_tool(
            "add_task",
            {"title": "Task to update", "priority": 2},
        )
        task_id = parse_result(add_result)["id"]

        update_result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "status": "done"},
        )

        assert not update_result.isError
        updated = parse_result(update_result)
        assert updated["status"] == "done"
        assert updated["completed_at"] is not None


@pytest.mark.asyncio
async def test_task_priority_sorting():
    async for session, _ in get_session():
        await session.call_tool("add_task", {"title": "Low priority", "priority": 1})
        await session.call_tool("add_task", {"title": "High priority", "priority": 3})
        await session.call_tool("add_task", {"title": "Normal priority", "priority": 2})

        result = await session.call_tool("list_tasks", {})
        tasks = parse_result(result, is_list_tool=True)

        priorities = [t["priority"] for t in tasks]
        assert priorities == sorted(priorities, reverse=True)


@pytest.mark.asyncio
async def test_due_datetime_with_time():
    async for session, _ in get_session():
        result = await session.call_tool(
            "add_task",
            {"title": "Task with time", "due": "tomorrow 3pm"},
        )

        assert not result.isError
        response = parse_result(result)
        assert response["due_date"] is not None
        assert "T15:00" in response["due_date"]


@pytest.mark.asyncio
async def test_due_datetime_defaults_to_9am():
    async for session, _ in get_session():
        result = await session.call_tool(
            "add_task",
            {"title": "Task without time", "due": "tomorrow"},
        )

        assert not result.isError
        response = parse_result(result)
        assert response["due_date"] is not None
        assert "T09:00" in response["due_date"]


@pytest.mark.asyncio
async def test_delete_task():
    async for session, _ in get_session():
        add_result = await session.call_tool(
            "add_task",
            {"title": "Task to delete"},
        )
        task_id = parse_result(add_result)["id"]

        delete_result = await session.call_tool("delete_task", {"task_id": task_id})
        assert not delete_result.isError

        list_result = await session.call_tool("list_tasks", {})
        tasks = parse_result(list_result, is_list_tool=True)
        assert not any(t["id"] == task_id for t in tasks)


@pytest.mark.asyncio
async def test_search_tasks():
    async for session, _ in get_session():
        await session.call_tool("add_task", {"title": "Find me please"})
        await session.call_tool("add_task", {"title": "Something else"})

        result = await session.call_tool("search_tasks", {"query": "Find"})
        assert not result.isError
        tasks = parse_result(result, is_list_tool=True)
        assert len(tasks) == 1
        assert "Find" in tasks[0]["title"]


@pytest.mark.asyncio
async def test_monitor_sends_notifications():
    """Test that monitor thread sends notifications for tasks due soon."""
    from datetime import timedelta

    async for session, notif_dir in get_session(with_notifications=True, monitor_interval=1):
        # Create a task due in 30 minutes (within 1 hour threshold)
        due_time = datetime.now() + timedelta(minutes=30)
        result = await session.call_tool(
            "add_task",
            {"title": "Urgent task", "due": due_time.strftime("%Y-%m-%dT%H:%M")},
        )
        assert not result.isError

        # Wait for monitor to run (checks every 1s in test mode)
        time.sleep(2)

        # Check notifications were created (multiple thresholds may fire)
        notif_files = list(notif_dir.glob("*-task-due.json"))
        assert len(notif_files) >= 1, f"Expected notification file, found: {list(notif_dir.iterdir())}"

        # Verify notification content structure
        notif = json.loads(notif_files[0].read_text())
        assert notif["source"] == "task"
        assert notif["type"] == "task_due"
        assert "Urgent task" in notif["message"]
        assert notif["metadata"]["reminder_window"] in ["1 week", "1 day", "1 hour", "15 minutes"]

        # Check that 1 hour notification exists (most specific for 30 min due time)
        windows = [json.loads(f.read_text())["metadata"]["reminder_window"] for f in notif_files]
        assert "1 hour" in windows, f"Expected '1 hour' notification, found: {windows}"


@pytest.mark.asyncio
async def test_monitor_no_notification_for_far_future_task():
    """Task due far in the future should not trigger notifications yet."""
    from datetime import timedelta

    async for session, notif_dir in get_session(with_notifications=True, monitor_interval=1):
        # Task due in 2 weeks (beyond 1 week threshold)
        due_time = datetime.now() + timedelta(weeks=2)
        result = await session.call_tool(
            "add_task",
            {"title": "Far future task", "due": due_time.strftime("%Y-%m-%dT%H:%M")},
        )
        assert not result.isError

        time.sleep(2)

        notif_files = list(notif_dir.glob("*-task-due.json"))
        assert len(notif_files) == 0, f"Expected no notifications, found: {[f.name for f in notif_files]}"


@pytest.mark.asyncio
async def test_monitor_no_notification_for_past_due_task():
    """Task already past due should not trigger new notifications."""
    from datetime import timedelta

    async for session, notif_dir in get_session(with_notifications=True, monitor_interval=1):
        # Task due 1 hour ago (already past)
        due_time = datetime.now() - timedelta(hours=1)
        result = await session.call_tool(
            "add_task",
            {"title": "Past due task", "due": due_time.strftime("%Y-%m-%dT%H:%M")},
        )
        assert not result.isError

        time.sleep(2)

        notif_files = list(notif_dir.glob("*-task-due.json"))
        assert len(notif_files) == 0, f"Expected no notifications for past task, found: {[f.name for f in notif_files]}"


@pytest.mark.asyncio
async def test_monitor_notification_deduplication():
    """Same threshold should not fire twice for the same task."""
    from datetime import timedelta

    async for session, notif_dir in get_session(with_notifications=True, monitor_interval=1):
        due_time = datetime.now() + timedelta(minutes=30)
        result = await session.call_tool(
            "add_task",
            {"title": "Dedup task", "due": due_time.strftime("%Y-%m-%dT%H:%M")},
        )
        assert not result.isError

        # Wait for multiple monitor cycles
        time.sleep(3)

        notif_files = list(notif_dir.glob("*-task-due.json"))
        # Count notifications per window - each should appear exactly once
        windows = [json.loads(f.read_text())["metadata"]["reminder_window"] for f in notif_files]
        for window in ["1 week", "1 day", "1 hour"]:
            count = windows.count(window)
            assert count <= 1, f"Window '{window}' fired {count} times, expected at most 1"


@pytest.mark.asyncio
async def test_due_datetime_today_with_various_times():
    """Test various time formats with 'today'."""
    async for session, _ in get_session():
        # 12-hour format with pm
        result = await session.call_tool("add_task", {"title": "Task 1", "due": "today 3pm"})
        assert "T15:00" in parse_result(result)["due_date"]

        # 24-hour format
        result = await session.call_tool("add_task", {"title": "Task 2", "due": "today 14:30"})
        assert "T14:30" in parse_result(result)["due_date"]

        # 12am edge case (midnight)
        result = await session.call_tool("add_task", {"title": "Task 3", "due": "today 12am"})
        assert "T00:00" in parse_result(result)["due_date"]

        # 12pm edge case (noon)
        result = await session.call_tool("add_task", {"title": "Task 4", "due": "today 12pm"})
        assert "T12:00" in parse_result(result)["due_date"]


@pytest.mark.asyncio
async def test_due_datetime_in_n_days():
    """Test 'in N days' format."""
    from datetime import timedelta

    async for session, _ in get_session():
        result = await session.call_tool("add_task", {"title": "Task", "due": "in 3 days"})
        response = parse_result(result)
        due_date = datetime.fromisoformat(response["due_date"])
        expected_date = (datetime.now() + timedelta(days=3)).date()
        assert due_date.date() == expected_date
        assert "T09:00" in response["due_date"]  # default time


@pytest.mark.asyncio
async def test_priority_string_inputs():
    """Test priority accepts 'low', 'normal', 'high' strings."""
    async for session, _ in get_session():
        result = await session.call_tool("add_task", {"title": "Low", "priority": "low"})
        assert parse_result(result)["priority"] == 1

        result = await session.call_tool("add_task", {"title": "Normal", "priority": "normal"})
        assert parse_result(result)["priority"] == 2

        result = await session.call_tool("add_task", {"title": "High", "priority": "high"})
        assert parse_result(result)["priority"] == 3


@pytest.mark.asyncio
async def test_get_task_by_id():
    """Test get_task tool returns correct task."""
    async for session, _ in get_session():
        add_result = await session.call_tool(
            "add_task",
            {"title": "Specific task", "priority": 3, "metadata": "test metadata"},
        )
        task_id = parse_result(add_result)["id"]

        get_result = await session.call_tool("get_task", {"task_id": task_id})
        assert not get_result.isError
        task = parse_result(get_result)
        assert task["id"] == task_id
        assert task["title"] == "Specific task"
        assert task["priority"] == 3
        assert task["metadata"] == "test metadata"


@pytest.mark.asyncio
async def test_get_task_not_found():
    """Test get_task returns error for non-existent task."""
    async for session, _ in get_session():
        result = await session.call_tool("get_task", {"task_id": "nonexistent"})
        assert result.isError


@pytest.mark.asyncio
async def test_update_task_metadata_append():
    """Test metadata appends by default."""
    async for session, _ in get_session():
        add_result = await session.call_tool(
            "add_task",
            {"title": "Task", "metadata": "initial note"},
        )
        task_id = parse_result(add_result)["id"]

        update_result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "metadata": "appended note"},
        )
        task = parse_result(update_result)
        assert "initial note" in task["metadata"]
        assert "appended note" in task["metadata"]


@pytest.mark.asyncio
async def test_update_task_metadata_replace():
    """Test metadata can replace instead of append."""
    async for session, _ in get_session():
        add_result = await session.call_tool(
            "add_task",
            {"title": "Task", "metadata": "initial note"},
        )
        task_id = parse_result(add_result)["id"]

        update_result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "metadata": "replaced note", "append_metadata": False},
        )
        task = parse_result(update_result)
        assert task["metadata"] == "replaced note"
        assert "initial" not in task["metadata"]


@pytest.mark.asyncio
async def test_update_task_reopen():
    """Test marking a completed task as pending clears completed_at."""
    async for session, _ in get_session():
        add_result = await session.call_tool("add_task", {"title": "Task"})
        task_id = parse_result(add_result)["id"]

        # Complete the task
        await session.call_tool("update_task", {"task_id": task_id, "status": "done"})

        # Reopen the task
        update_result = await session.call_tool(
            "update_task",
            {"task_id": task_id, "status": "pending"},
        )
        task = parse_result(update_result)
        assert task["status"] == "pending"
        assert task["completed_at"] is None


@pytest.mark.asyncio
async def test_list_tasks_show_completed():
    """Test show_completed flag includes done tasks."""
    async for session, _ in get_session():
        add_result = await session.call_tool("add_task", {"title": "Will complete"})
        task_id = parse_result(add_result)["id"]
        await session.call_tool("update_task", {"task_id": task_id, "status": "done"})

        # Default: completed tasks hidden
        result = await session.call_tool("list_tasks", {})
        tasks = parse_result(result, is_list_tool=True)
        assert not any(t["id"] == task_id for t in tasks)

        # With show_completed: includes done tasks
        result = await session.call_tool("list_tasks", {"show_completed": True})
        tasks = parse_result(result, is_list_tool=True)
        assert any(t["id"] == task_id for t in tasks)


@pytest.mark.asyncio
async def test_search_tasks_show_completed():
    """Test search respects show_completed flag."""
    async for session, _ in get_session():
        add_result = await session.call_tool("add_task", {"title": "Findable task"})
        task_id = parse_result(add_result)["id"]
        await session.call_tool("update_task", {"task_id": task_id, "status": "done"})

        # Default: completed tasks hidden from search
        result = await session.call_tool("search_tasks", {"query": "Findable"})
        tasks = parse_result(result, is_list_tool=True)
        assert len(tasks) == 0

        # With show_completed
        result = await session.call_tool("search_tasks", {"query": "Findable", "show_completed": True})
        tasks = parse_result(result, is_list_tool=True)
        assert len(tasks) == 1


@pytest.mark.asyncio
async def test_notification_includes_priority():
    """Test notification message includes correct priority label."""
    from datetime import timedelta

    async for session, notif_dir in get_session(with_notifications=True, monitor_interval=1):
        due_time = datetime.now() + timedelta(minutes=30)
        await session.call_tool(
            "add_task",
            {"title": "High priority task", "due": due_time.strftime("%Y-%m-%dT%H:%M"), "priority": 3},
        )

        time.sleep(2)

        notif_files = list(notif_dir.glob("*-task-due.json"))
        assert len(notif_files) >= 1
        notif = json.loads(notif_files[0].read_text())
        assert "high priority" in notif["message"]
        assert notif["metadata"]["priority"] == 3


@pytest.mark.asyncio
async def test_completed_task_no_notifications():
    """Completed tasks should not trigger notifications."""
    from datetime import timedelta

    async for session, notif_dir in get_session(with_notifications=True, monitor_interval=1):
        due_time = datetime.now() + timedelta(minutes=30)
        add_result = await session.call_tool(
            "add_task",
            {"title": "Completed task", "due": due_time.strftime("%Y-%m-%dT%H:%M")},
        )
        task_id = parse_result(add_result)["id"]

        # Mark as done before monitor runs
        await session.call_tool("update_task", {"task_id": task_id, "status": "done"})

        time.sleep(2)

        notif_files = list(notif_dir.glob("*-task-due.json"))
        assert len(notif_files) == 0, "Completed task should not trigger notifications"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
