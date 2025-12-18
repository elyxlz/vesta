"""What Day skill template."""

SKILL_MD = """\
---
name: what-day
description: This skill should be used when working with ANY date to determine what day of the week it falls on. Use this skill when the user mentions dates, scheduling, planning events, or needs to know day-of-week information.
---

# What Day

## Purpose

CRITICAL: Use this skill when working with ANY date to avoid mistakes about which day of the week it falls on. This prevents scheduling errors and date-related planning mistakes.

## How to Determine Day of Week

Run the script to get day-of-week information:

```bash
uv run scripts/what_day.py 2025-11-14
```

Output:
```json
{
  "date": "2025-11-14",
  "day_of_week": "Friday",
  "formatted": "November 14, 2025",
  "full_description": "November 14, 2025 is a Friday",
  "today": "December 18, 2025 (Thursday)"
}
```

## When to Use

- When a date is mentioned in conversation
- When planning or scheduling events
- When discussing deadlines or appointments
- When comparing dates or calculating intervals
- When verifying day-of-week for any date reference

## Examples

- "2025-11-14" -> "November 14, 2025 is a Friday"
- "2024-12-25" -> "December 25, 2024 is a Wednesday"
- "2023-01-01" -> "January 01, 2023 is a Sunday"

## Learned Patterns

### Common Date Queries
[Frequently asked date patterns]

### User Preferences
[Preferred date formats, timezone considerations]
"""

SCRIPTS: dict[str, str] = {
    "what_day.py": '''\
#!/usr/bin/env python3
"""Get day of week for a given date."""

import json
import sys
from datetime import datetime


def what_day(date: str) -> dict[str, str]:
    """Return day-of-week info for a date in YYYY-MM-DD format."""
    parsed = datetime.strptime(date, "%Y-%m-%d")
    day_name = parsed.strftime("%A")
    formatted = parsed.strftime("%B %d, %Y")
    today = datetime.now()
    today_str = today.strftime("%B %d, %Y (%A)")

    return {
        "date": date,
        "day_of_week": day_name,
        "formatted": formatted,
        "full_description": f"{formatted} is a {day_name}",
        "today": today_str,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: what_day.py YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    result = what_day(sys.argv[1])
    print(json.dumps(result, indent=2))
''',
}
