"""Scheduler MCP server entry point"""

import argparse
from pathlib import Path
from .tools import mcp


def main():
    parser = argparse.ArgumentParser(description="Scheduler MCP Server")
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory for storing persistent data (database, logs)"
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

    from . import scheduler as scheduler_module
    from . import tools

    scheduler = scheduler_module.create_scheduler(data_dir)
    tools.init_tools(scheduler, data_dir, notifications_dir)

    print(f"Scheduler MCP started - data: {data_dir}, notifications: {notifications_dir}")
    mcp.run()


if __name__ == "__main__":
    main()
