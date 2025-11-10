"""Server entry point for what-day MCP."""

from .tools import mcp


def main() -> None:
    """Run the what-day MCP server."""
    mcp.run()
