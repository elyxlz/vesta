#!/usr/bin/env python
"""Simple test to verify scheduler MCP works"""

from datetime import datetime, timedelta
from pathlib import Path
import sys
import pytest
import tempfile

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scheduler_mcp.tools import set_reminder, list_reminders, cancel_reminder
from scheduler_mcp import tools, scheduler as scheduler_module


@pytest.fixture(scope="session", autouse=True)
def setup_scheduler():
    """Initialize scheduler before running tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        notif_dir = Path(tmpdir) / "notifications"
        data_dir.mkdir(parents=True, exist_ok=True)
        notif_dir.mkdir(parents=True, exist_ok=True)

        scheduler = scheduler_module.create_scheduler(data_dir)
        scheduler.start()
        tools.init_tools(scheduler, data_dir, notif_dir)

        yield

        scheduler.shutdown()


def test_set_reminder():
    """Test setting a reminder"""
    # Test with minutes
    result = set_reminder(message="Test reminder in 5 minutes", minutes=5)
    assert "id" in result
    assert result["status"] == "scheduled"
    print(f"✓ Created reminder: {result['id']}")

    # Test with datetime
    future_time = datetime.now() + timedelta(hours=1)
    result2 = set_reminder(message="Test at specific time", datetime=future_time.isoformat())
    assert "id" in result2
    assert result2["status"] == "scheduled"
    print(f"✓ Created timed reminder: {result2['id']}")

    return result["id"], result2["id"]


def test_list_reminders():
    """Test listing reminders"""
    reminders = list_reminders()
    assert isinstance(reminders, list)
    print(f"✓ Listed {len(reminders)} reminders")
    return reminders


def cancel_reminder_helper(reminder_id):
    """Helper to cancel a reminder"""
    result = cancel_reminder(reminder_id)
    assert result["status"] == "cancelled"
    print(f"✓ Cancelled reminder: {reminder_id}")


def main():
    print("Testing Scheduler MCP...")

    # Create reminders
    id1, id2 = test_set_reminder()

    # List them
    reminders = test_list_reminders()
    assert len(reminders) >= 2

    # Cancel them
    cancel_reminder_helper(id1)
    cancel_reminder_helper(id2)

    # Verify they're gone
    final_reminders = list_reminders()
    remaining_ids = [r["id"] for r in final_reminders]
    assert id1 not in remaining_ids
    assert id2 not in remaining_ids

    print("\n✅ All tests passed!")


if __name__ == "__main__":
    main()
