"""What Day CLI - Date to day-of-week conversion."""

import argparse
import json
import sys
from datetime import datetime


def check(date: str) -> dict[str, str]:
    try:
        parsed_date = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format. Expected YYYY-MM-DD (e.g., '2025-11-14'), got '{date}'")

    day_name = parsed_date.strftime("%A")
    formatted = parsed_date.strftime("%B %d, %Y")
    today = datetime.now()
    today_str = today.strftime("%B %d, %Y (%A)")
    full_description = f"{formatted} is a {day_name}"

    return {
        "date": date,
        "day_of_week": day_name,
        "formatted": formatted,
        "full_description": full_description,
        "today": today_str,
    }


def main():
    parser = argparse.ArgumentParser(prog="what-day")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check", help="Check what day of the week a date falls on")
    p.add_argument("date", help="Date in YYYY-MM-DD format")

    args = parser.parse_args()

    try:
        if args.command == "check":
            result = check(args.date)
            print(json.dumps(result, indent=2))
    except ValueError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
