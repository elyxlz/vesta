import os
import sys
import threading
import logging
from .tools import mcp
from .monitor import run as run_monitor

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        print(
            "Error: MICROSOFT_MCP_CLIENT_ID environment variable is required",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info("Starting Microsoft MCP server")
    logger.info(f"NOTIFICATIONS_DIR: {os.getenv('NOTIFICATIONS_DIR', 'Not set')}")

    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    logger.info("Microsoft Graph notification monitor thread started")

    mcp.run()


if __name__ == "__main__":
    main()
