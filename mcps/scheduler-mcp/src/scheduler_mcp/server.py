"""Scheduler MCP server entry point"""

from .tools import mcp

def main():
    print("Scheduler MCP started - ready to schedule reminders")
    mcp.run()

if __name__ == "__main__":
    main()