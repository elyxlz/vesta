#!/usr/bin/env python
"""Simple test to verify scheduler MCP works"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from scheduler_mcp.tools import set_reminder, list_reminders, cancel_reminder


def test_set_reminder():
    """Test setting a reminder"""
    # Test with minutes
    result = set_reminder(
        message="Test reminder in 5 minutes",
        minutes=5
    )
    assert "reminder_id" in result
    assert result["status"] == "scheduled"
    print(f"✓ Created reminder: {result['reminder_id']}")
    
    # Test with datetime
    future_time = datetime.now() + timedelta(hours=1)
    result2 = set_reminder(
        message="Test at specific time",
        datetime=future_time.isoformat()
    )
    assert "reminder_id" in result2
    assert result2["status"] == "scheduled"
    print(f"✓ Created timed reminder: {result2['reminder_id']}")
    
    return result["reminder_id"], result2["reminder_id"]


def test_list_reminders():
    """Test listing reminders"""
    reminders = list_reminders()
    assert isinstance(reminders, list)
    print(f"✓ Listed {len(reminders)} reminders")
    return reminders


def test_cancel_reminder(reminder_id):
    """Test canceling a reminder"""
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
    test_cancel_reminder(id1)
    test_cancel_reminder(id2)
    
    # Verify they're gone
    final_reminders = list_reminders()
    remaining_ids = [r["id"] for r in final_reminders]
    assert id1 not in remaining_ids
    assert id2 not in remaining_ids
    
    print("\n✅ All tests passed!")


if __name__ == "__main__":
    main()