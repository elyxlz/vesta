"""WhatsApp MCP server entry point"""

import argparse
import sys
from pathlib import Path
from .tools import mcp


def main():
    parser = argparse.ArgumentParser(description="WhatsApp MCP Server")
    parser.add_argument(
        "--data-dir",
        type=str,
        required=True,
        help="Directory for storing persistent data (database copies)"
    )
    parser.add_argument(
        "--notifications-dir",
        type=str,
        required=False,
        help="Directory for writing notifications (optional)"
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    from . import whatsapp
    whatsapp.init_whatsapp(data_dir / "messages.db")

    if args.notifications_dir:
        notifications_dir = Path(args.notifications_dir).resolve()
        notifications_dir.mkdir(parents=True, exist_ok=True)

    print(f"WhatsApp MCP started - data: {data_dir}")
    mcp.run()


if __name__ == "__main__":
    main()