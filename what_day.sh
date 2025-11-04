#!/bin/bash

# Script to check what day of the week a date falls on
# Usage: ./what_day.sh YYYY-MM-DD
# Example: ./what_day.sh 2025-10-10

if [ $# -eq 0 ]; then
    echo "Usage: $0 YYYY-MM-DD"
    echo "Example: $0 2025-10-10"
    exit 1
fi

DATE_INPUT="$1"

# Validate date format
if ! date -d "$DATE_INPUT" >/dev/null 2>&1; then
    echo "Error: Invalid date format. Use YYYY-MM-DD"
    exit 1
fi

# Get day of week
DAY_OF_WEEK=$(date -d "$DATE_INPUT" +"%A")
DATE_FORMATTED=$(date -d "$DATE_INPUT" +"%B %d, %Y")

echo "$DATE_FORMATTED is a $DAY_OF_WEEK"

# Also show today for reference
TODAY=$(date +"%A, %B %d, %Y")
echo "Today is $TODAY"