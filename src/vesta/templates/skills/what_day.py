"""What Day skill template."""

from pathlib import Path

_SCRIPTS_DIR = Path(__file__).parent / "scripts"

SKILL_MD = """\
---
name: what-day
description: This skill should be used when working with ANY date to determine what day of the week it falls on. Use this skill when the user mentions dates, scheduling, planning events, or needs to know day-of-week information.
---

# What Day

## Purpose

CRITICAL: Use this skill when working with ANY date to avoid mistakes about which day of the week it falls on. This prevents scheduling errors and date-related planning mistakes.

## How to Determine Day of Week

```bash
uv run memory/skills/what-day/scripts/what_day.py 2025-11-14
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

SCRIPTS = {
    "what_day.py": (_SCRIPTS_DIR / "what_day.py").read_text(),
}
