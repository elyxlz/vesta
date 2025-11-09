import sys
import pytest
import json
import tempfile
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def parse_result(result, is_list_tool=False):
    """Helper to parse MCP tool results consistently"""
    if result.content and hasattr(result.content[0], "text"):
        text = result.content[0].text
        if text == "[]":
            return []
        data = json.loads(text)
        # FastMCP may unwrap single-element lists for list tools
        if is_list_tool and isinstance(data, dict):
            return [data]
        return data
    return []


async def get_session():
    """Create MCP client session for testing"""
    # Create temporary directory for data
    test_dir = Path(tempfile.mkdtemp(prefix="task_mcp_test_"))
    data_dir = test_dir / "data"
    data_dir.mkdir(parents=True)

    server_params = StdioServerParameters(
        command="uv",
        args=["run", "task-mcp", "--data-dir", str(data_dir)],
        cwd=str(Path(__file__).parent.parent),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


@pytest.mark.asyncio
async def test_add_and_list_task():
    """Test adding a task and listing it"""
    async for session in get_session():
        # Add a task
        result = await session.call_tool(
            "add_task",
            {
                "title": "Test task",
                "priority": 3,
                "due": "tomorrow",
            },
        )

        assert not result.isError
        response = parse_result(result)
        task_id = response["id"]
        assert response["title"] == "Test task"
        assert response["priority"] == 3
        assert response["status"] == "pending"

        # List tasks
        list_result = await session.call_tool("list_tasks", {})
        assert not list_result.isError
        tasks = parse_result(list_result, is_list_tool=True)
        assert len(tasks) >= 1
        assert any(t["id"] == task_id for t in tasks)


@pytest.mark.asyncio
async def test_update_task():
    """Test updating a task"""
    async for session in get_session():
        # Add a task
        add_result = await session.call_tool(
            "add_task",
            {"title": "Task to update", "priority": 2},
        )
        task_id = parse_result(add_result)["id"]

        # Update to done
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
    """Test that tasks are sorted by priority"""
    async for session in get_session():
        # Add tasks with different priorities
        await session.call_tool("add_task", {"title": "Low priority", "priority": 1})
        await session.call_tool("add_task", {"title": "High priority", "priority": 3})
        await session.call_tool("add_task", {"title": "Normal priority", "priority": 2})

        # List tasks
        result = await session.call_tool("list_tasks", {})
        tasks = parse_result(result, is_list_tool=True)

        # Should be sorted by priority DESC (3, 2, 1)
        priorities = [t["priority"] for t in tasks]
        assert priorities == sorted(priorities, reverse=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
