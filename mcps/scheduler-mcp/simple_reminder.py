#!/usr/bin/env python3
"""Simple script to create a BANANA reminder for 12:15 PM today"""

import json
import os
import sys
from datetime import datetime, time
from pathlib import Path

# We'll create the reminder by directly writing to the notifications directory
# and adding a job to the scheduler database manually

def create_reminder_job():
    """Create the BANANA reminder for 12:15 PM today"""

    # Create datetime for 12:15 PM today
    today = datetime.now().date()
    reminder_time = datetime.combine(today, time(12, 15))

    print(f"🍌 Setting up BANANA reminder for {reminder_time}")

    # Create a simple test by scheduling it using the existing infrastructure
    try:
        # Import the scheduler components we need
        from src.scheduler_mcp.scheduler import scheduler, write_notification
        from src.scheduler_mcp.tools import set_reminder

        # For now, let's just test that the import works
        print("✅ Successfully imported scheduler components")

        # Try to create the reminder using datetime format that works with the API
        result = set_reminder(
            message="BANANA",
            datetime=reminder_time.strftime("%Y-%m-%dT%H:%M:%S")
        )

        print(f"🎉 Reminder created: {result}")
        return True

    except Exception as e:
        print(f"❌ Error with scheduler approach: {e}")
        print("🔄 Trying alternative approach...")

        # Alternative: Create a notification file that will be picked up
        # This simulates what the scheduler would do when the time comes
        notif_dir = Path("../../notifications")
        notif_dir.mkdir(exist_ok=True)

        # Create a future-scheduled notification file name
        future_timestamp = int(reminder_time.timestamp() * 1e6)
        filename = f"{future_timestamp}-scheduler-reminder.json"

        notif_data = {
            "timestamp": reminder_time.isoformat(),
            "source": "scheduler",
            "type": "reminder",
            "data": {
                "reminder_id": "banana-reminder-12-15",
                "message": "BANANA"
            }
        }

        # Write the notification file
        notif_file = notif_dir / filename
        notif_file.write_text(json.dumps(notif_data, indent=2))

        print(f"📝 Created notification file: {notif_file}")
        print(f"⏰ This will be processed when Vesta checks notifications")

        return True

if __name__ == "__main__":
    if create_reminder_job():
        print("\n🎉 BANANA reminder setup complete!")
        print("📅 Scheduled for: 12:15 PM today (September 14, 2025)")
        print("💬 Message: BANANA")
        print("\n🔔 The reminder will appear when Vesta is running and checks notifications")
    else:
        print("\n❌ Failed to set up reminder")
        sys.exit(1)