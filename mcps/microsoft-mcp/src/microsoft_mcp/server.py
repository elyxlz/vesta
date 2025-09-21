import os
import sys
import threading
import logging
import argparse
from pathlib import Path
from .tools import mcp
from .monitor import run as run_monitor
from . import auth

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Microsoft MCP Server")
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory for storing persistent data (tokens, logs, state)"
    )
    parser.add_argument(
        "--notifications-dir",
        type=str,
        required=True,
        help="Directory for writing notifications"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    notifications_dir = Path(args.notifications_dir).resolve()
    notifications_dir.mkdir(parents=True, exist_ok=True)

    from . import monitor, notifications
    auth.init_auth(data_dir / "token_cache.json")
    monitor.init_monitor(data_dir, data_dir / "last_check", data_dir / "monitor.log")
    notifications.init_notifications(notifications_dir)

    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        print(
            "Error: MICROSOFT_MCP_CLIENT_ID environment variable is required",
            file=sys.stderr,
        )
        sys.exit(1)

    logger.info("Starting Microsoft MCP server")
    logger.info(f"Data directory: {data_dir}")
    logger.info(f"NOTIFICATIONS_DIR: {os.getenv('NOTIFICATIONS_DIR', 'Not set')}")

    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    logger.info("Microsoft Graph notification monitor thread started")

    mcp.run()


if __name__ == "__main__":
    main()
