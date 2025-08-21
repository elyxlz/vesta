#!/bin/bash
# Simple hook to add current datetime to every prompt

# Read input from stdin
input=$(cat)

# Get current date
datetime=$(date)

# Output JSON with additional context
cat <<EOF
{
  "additional_context": "Current date and time: $datetime"
}
EOF