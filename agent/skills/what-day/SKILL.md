---
name: what-day
description: Determine the day of the week for any date, always do this whenever mentioning or reasoning through weekdays and dates.
---

# What Day

Run this whenever a date's weekday matters, so scheduling and planning never rest on a guessed day of the week.

## Setup

```bash
uv tool install --editable ~/agent/skills/what-day/cli
```

## Usage

```bash
what-day 2025-11-14
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

## Learned Patterns

### Common Date Queries
[Frequently asked date patterns]

### User Preferences
[Preferred date formats, timezone considerations]
