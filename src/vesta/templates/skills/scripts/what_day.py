#!/usr/bin/env python3
import json
import sys
from datetime import datetime

if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} YYYY-MM-DD", file=sys.stderr)
    sys.exit(1)

date = sys.argv[1]
try:
    parsed_date = datetime.strptime(date, "%Y-%m-%d")
except ValueError:
    print(json.dumps({"error": f"Invalid date format. Expected YYYY-MM-DD, got '{date}'"}), file=sys.stderr)
    sys.exit(1)

day_name = parsed_date.strftime("%A")
formatted = parsed_date.strftime("%B %d, %Y")
today = datetime.now()
today_str = today.strftime("%B %d, %Y (%A)")

print(json.dumps({
    "date": date,
    "day_of_week": day_name,
    "formatted": formatted,
    "full_description": f"{formatted} is a {day_name}",
    "today": today_str,
}, indent=2))
