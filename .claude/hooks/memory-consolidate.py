#!/usr/bin/env python3

import json
import sys
from pathlib import Path

# Read hook input
input_data = json.loads(sys.stdin.read())
transcript_path = Path(input_data["transcript_path"])

# Read current memory
memory_file = Path("CLAUDE.md")
current_memory = memory_file.read_text() if memory_file.exists() else ""

# Read transcript
transcript = transcript_path.read_text()

# Extract key learnings (simple version - just look for corrections and important patterns)
new_learnings = []

# Look for user corrections
if (
    "don't" in transcript.lower()
    or "remember" in transcript.lower()
    or "always" in transcript.lower()
):
    lines = transcript.split("\n")
    for i, line in enumerate(lines):
        if any(
            word in line.lower()
            for word in ["don't", "remember", "always", "never", "should"]
        ):
            new_learnings.append(line.strip())

# Append new learnings to memory
if new_learnings:
    memory_file.write_text(
        current_memory + "\n\n## Session Learnings\n" + "\n".join(new_learnings)
    )

# Return success
print(json.dumps({"status": "Memory consolidated"}))
sys.exit(0)
