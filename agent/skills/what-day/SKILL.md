---
name: what-day
description: Determine the day of the week for any date, always do this whenever mentioning or reasoning through weekdays and dates.
---

# What Day

Use whenever working with a date, to avoid mistakes about which weekday it falls on and prevent scheduling errors.

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

## When to Use

- A date is mentioned in conversation
- Planning or scheduling events, deadlines, appointments
- Comparing dates or calculating intervals
- Verifying day-of-week for any date reference

## Learned Patterns

### Common Date Queries
[Frequently asked date patterns]

### User Preferences
[Preferred date formats, timezone considerations]
