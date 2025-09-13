import os
import sys
import threading
from .tools import mcp
from .monitor import run as run_monitor


def main() -> None:
    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        print(
            "Error: MICROSOFT_MCP_CLIENT_ID environment variable is required",
            file=sys.stderr,
        )
        sys.exit(1)

    # Start notification monitor in background thread
    monitor_thread = threading.Thread(target=run_monitor, daemon=True)
    monitor_thread.start()
    print("Microsoft Graph notification monitor started")

    mcp.run()


if __name__ == "__main__":
    main()
