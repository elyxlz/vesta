#!/usr/bin/env python
"""Simple test to verify scheduler MCP works"""

from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass
import sys
import pytest
import tempfile

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scheduler_mcp.tools import set_reminder, list_reminders, cancel_reminder, SchedulerContext, init_db, check_missed_reminders
from scheduler_mcp import scheduler as scheduler_module


@dataclass
class MockRequestContext:
    lifespan_context: SchedulerContext


@dataclass
class MockContext:
    request_context: MockRequestContext


@pytest.fixture(scope="session")
def scheduler_context():
    """Create a test scheduler context"""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        notif_dir = Path(tmpdir) / "notifications"
        data_dir.mkdir(parents=True, exist_ok=True)
        notif_dir.mkdir(parents=True, exist_ok=True)

        scheduler = scheduler_module.create_scheduler(data_dir)
        scheduler.start()

        ctx = SchedulerContext(scheduler, data_dir, notif_dir)
        init_db(ctx)
        check_missed_reminders(ctx)

        yield ctx

        scheduler.shutdown()


@pytest.fixture(scope="session")
def mock_ctx(scheduler_context):
    """Create a mock Context for tool functions"""
    return MockContext(request_context=MockRequestContext(lifespan_context=scheduler_context))


def test_set_reminder(mock_ctx):
    """Test setting a reminder"""
    # Test with minutes
    result = set_reminder(mock_ctx, message="Test reminder in 5 minutes", minutes=5)
    assert "id" in result
    assert result["status"] == "scheduled"
    print(f"✓ Created reminder: {result['id']}")

    # Test with datetime
    future_time = datetime.now() + timedelta(hours=1)
    result2 = set_reminder(mock_ctx, message="Test at specific time", datetime=future_time.isoformat())
    assert "id" in result2
    assert result2["status"] == "scheduled"
    print(f"✓ Created timed reminder: {result2['id']}")

    return result["id"], result2["id"]


def test_list_reminders(mock_ctx):
    """Test listing reminders"""
    reminders = list_reminders(mock_ctx)
    assert isinstance(reminders, list)
    print(f"✓ Listed {len(reminders)} reminders")
    return reminders


def cancel_reminder_helper(mock_ctx, reminder_id):
    """Helper to cancel a reminder"""
    result = cancel_reminder(mock_ctx, reminder_id)
    assert result["status"] == "cancelled"
    print(f"✓ Cancelled reminder: {reminder_id}")


def main():
    print("Testing Scheduler MCP...")

    # Create test context
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        notif_dir = Path(tmpdir) / "notifications"
        data_dir.mkdir(parents=True, exist_ok=True)
        notif_dir.mkdir(parents=True, exist_ok=True)

        scheduler = scheduler_module.create_scheduler(data_dir)
        scheduler.start()

        ctx_obj = SchedulerContext(scheduler, data_dir, notif_dir)
        init_db(ctx_obj)
        check_missed_reminders(ctx_obj)

        mock_context = MockContext(request_context=MockRequestContext(lifespan_context=ctx_obj))

        try:
            # Create reminders
            id1, id2 = test_set_reminder(mock_context)

            # List them
            reminders = test_list_reminders(mock_context)
            assert len(reminders) >= 2

            # Cancel them
            cancel_reminder_helper(mock_context, id1)
            cancel_reminder_helper(mock_context, id2)

            # Verify they're gone
            final_reminders = list_reminders(mock_context)
            remaining_ids = [r["id"] for r in final_reminders]
            assert id1 not in remaining_ids
            assert id2 not in remaining_ids

            print("\n✅ All tests passed!")
        finally:
            scheduler.shutdown()


if __name__ == "__main__":
    main()
