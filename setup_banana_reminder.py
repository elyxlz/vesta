#!/usr/bin/env python3
"""Set up BANANA reminder for 12:15 PM today using MCP tools"""

import asyncio
import sys
from datetime import datetime, time
from pathlib import Path

# Add the MCP directory to path
mcp_path = Path(__file__).parent / "mcps" / "scheduler-mcp" / "src"
sys.path.insert(0, str(mcp_path))

async def setup_banana_reminder():
    """Set up the BANANA reminder"""
    print("🍌 Setting up BANANA reminder for 12:15 PM today...")

    # Create datetime for 12:15 PM today
    today = datetime.now().date()
    reminder_time = datetime.combine(today, time(12, 15))

    print(f"📅 Target time: {reminder_time}")
    print(f"🕐 Current time: {datetime.now()}")

    try:
        # Import scheduler components
        from scheduler_mcp.scheduler import scheduler, write_notification
        from scheduler_mcp.tools import set_reminder

        # Start the scheduler in async mode
        print("🚀 Starting scheduler...")

        # Create event loop for scheduler
        loop = asyncio.get_event_loop()
        scheduler.start()

        print("✅ Scheduler started successfully")

        # Create the reminder
        result = set_reminder(
            message="BANANA",
            datetime=reminder_time.isoformat()
        )

        print(f"🎉 Reminder created successfully!")
        print(f"📋 Result: {result}")

        # Wait a moment to ensure persistence
        await asyncio.sleep(2)

        # Shutdown gracefully
        scheduler.shutdown(wait=True)
        print("🛑 Scheduler shut down cleanly")

        return True

    except Exception as e:
        print(f"❌ Error setting up reminder: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main function"""
    print("🍌 BANANA Reminder Setup")
    print("=" * 40)

    success = asyncio.run(setup_banana_reminder())

    if success:
        print("\n🎉 SUCCESS!")
        print("📝 Your BANANA reminder has been scheduled for 12:15 PM today")
        print("🔔 It will trigger when Vesta is running and monitoring notifications")
        print("\n📋 Summary:")
        print(f"   • Time: 12:15 PM (September 14, 2025)")
        print(f"   • Message: BANANA")
        print(f"   • Type: One-time reminder")
    else:
        print("\n❌ FAILED!")
        print("Could not set up the reminder. Please check the error messages above.")
        sys.exit(1)

if __name__ == "__main__":
    main()