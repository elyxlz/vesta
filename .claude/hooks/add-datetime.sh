#!/bin/bash
# Hook to add current datetime to every user prompt

# Read input from stdin (required but not used)
input=$(cat)

# Get current datetime with nice formatting
datetime=$(date '+%Y-%m-%d %H:%M:%S (%A)')

# Output JSON with additional context
cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "[Current time: $datetime]"
  }
}
EOF