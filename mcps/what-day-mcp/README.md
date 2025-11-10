# What Day MCP

**CRITICAL: This MCP should ALWAYS be used when working with dates to avoid mistakes about which day of the week they fall on.**

A simple, stateless MCP that converts dates to day-of-week information. Humans frequently make mistakes about which day of the week a date falls on - this tool provides accurate day-of-week calculations.

## Purpose

**USE THIS TOOL AUTOMATICALLY** whenever:
- A date is mentioned in conversation (e.g., "November 14th, 2025")
- Scheduling or planning around specific dates
- Discussing events on particular dates
- ANY date-related conversation where the day of the week matters

## Installation

This MCP is designed to run within the Vesta ecosystem. It's automatically registered in `src/vesta/models.py`.

```bash
# Run from the project root
uv run --directory mcps/what-day-mcp what-day-mcp
```

## Tools

### what_day

**ALWAYS use this tool when working with ANY date.**

Takes a date and returns comprehensive day-of-week information.

**Input:**
- `date` (string, required): Date in YYYY-MM-DD format (e.g., "2025-11-14")

**Output:**
```json
{
  "date": "2025-11-14",
  "day_of_week": "Friday",
  "formatted": "November 14, 2025",
  "full_description": "November 14, 2025 is a Friday",
  "today": "November 09, 2025 (Saturday)"
}
```

**Examples:**
```python
# Check what day Christmas 2025 falls on
what_day("2025-12-25")
# Returns: "December 25, 2025 is a Thursday"

# Check New Year's Day 2026
what_day("2026-01-01")
# Returns: "January 01, 2026 is a Thursday"

# Verify a meeting date
what_day("2025-11-14")
# Returns: "November 14, 2025 is a Friday"
```

## Architecture

This is a stateless MCP with minimal structure:

- **No persistent storage** - Pure date calculations
- **No configuration** - Works out of the box
- **Fast & reliable** - Uses Python's built-in `datetime` module
- **No external dependencies** - Just FastMCP

## Why This Exists

Date calculations are error-prone for humans. This MCP ensures:
1. Accurate day-of-week calculations
2. Consistent date formatting
3. Context (today's date) for reference
4. Proper date validation

## Development

```bash
# Install dependencies
cd mcps/what-day-mcp
uv sync

# Run tests (when added)
uv run python -m pytest tests/ -v
```

## License

Part of the Vesta project.
