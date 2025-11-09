"""What Day MCP - Date to day-of-week conversion.

CRITICAL: This MCP should ALWAYS be used when working with any date
to avoid mistakes about which day of the week it falls on.
"""

from datetime import datetime

from mcp.server.fastmcp import Context, FastMCP

from .context import what_day_lifespan

mcp = FastMCP("what-day", lifespan=what_day_lifespan)


@mcp.tool(
    description=(
        "ALWAYS use this tool when working with ANY date to determine what day of the week it falls on. "
        "This prevents mistakes in scheduling and date-related planning. "
        "Takes a date in YYYY-MM-DD format and returns the day of the week plus context. "
        "Examples: '2025-11-14', '2024-12-25', '2023-01-01'. "
        "USE THIS TOOL AUTOMATICALLY whenever a date is mentioned in conversation."
    )
)
def what_day(ctx: Context, date: str) -> dict[str, str]:
    """Determine what day of the week a given date falls on.

    CRITICAL: Use this tool for ALL date references to avoid day-of-week mistakes.

    Args:
        date: Date in YYYY-MM-DD format (e.g., "2025-11-14")

    Returns:
        Dictionary containing:
        - date: The input date
        - day_of_week: The day name (e.g., "Friday")
        - formatted: Human-readable format (e.g., "November 14, 2025")
        - full_description: Complete sentence (e.g., "November 14, 2025 is a Friday")
        - today: Today's date for reference

    Raises:
        ValueError: If date format is invalid or date doesn't exist
    """
    # Parse date
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"Invalid date format. Expected YYYY-MM-DD (e.g., '2025-11-14'), got '{date}'") from e

    # Get day of week
    day_name = parsed_date.strftime("%A")

    # Get human-readable format
    formatted = parsed_date.strftime("%B %d, %Y")

    # Get today for context
    today = datetime.now()
    today_str = today.strftime("%B %d, %Y (%A)")

    # Build full description
    full_description = f"{formatted} is a {day_name}"

    return {
        "date": date,
        "day_of_week": day_name,
        "formatted": formatted,
        "full_description": full_description,
        "today": today_str,
    }
