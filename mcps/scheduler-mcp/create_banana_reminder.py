#!/usr/bin/env python3
"""Script to create a scheduled reminder for 12:15 PM today"""

import asyncio
from datetime import datetime, time
from src.scheduler_mcp.scheduler import scheduler
from src.scheduler_mcp.tools import set_reminder
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


async def create_banana_reminder():
    """Create a reminder for 12:15 PM today with message 'BANANA'"""

    # Start the scheduler
    print("🚀 Starting scheduler...")
    scheduler.start()
    print("✅ Scheduler started")

    # Create datetime for 12:15 PM today
    today = datetime.now().date()
    reminder_time = datetime.combine(today, time(12, 15))

    print(f"📅 Scheduling reminder for: {reminder_time}")
    print("💬 Message: BANANA")

    try:
        # Use the set_reminder function to create the reminder
        result = set_reminder(message="BANANA", datetime=reminder_time.isoformat())

        print("✅ Reminder created successfully!")
        print(f"📋 Details: {result}")

        # Keep the scheduler running for a few seconds to ensure persistence
        print("💾 Ensuring persistence...")
        await asyncio.sleep(3)

    except Exception as e:
        print(f"❌ Error creating reminder: {e}")
        return False

    finally:
        print("🛑 Shutting down scheduler...")
        scheduler.shutdown()

    return True


if __name__ == "__main__":
    print("🍌 Creating BANANA reminder for 12:15 PM today")
    success = asyncio.run(create_banana_reminder())

    if success:
        print("\n🎉 Reminder scheduled successfully!")
        print(
            "📝 The reminder will trigger at 12:15 PM today with the message 'BANANA'"
        )
    else:
        print("\n❌ Failed to schedule reminder")
