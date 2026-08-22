#!/bin/sh
file="$HOME/agent/MEMORY.md"
# Bytes, not characters. MEMORY.md carries multi-byte UTF-8 (section signs, arrows,
# accented names), so Python's len() reads LOWER than the real size and a file that
# looks like it has headroom can already be over. Report the unit that is measured.
bytes=$(wc -c < "$file")
limit=50000
pct=$((bytes * 100 / limit))
echo "${bytes}/${limit} bytes (${pct}%)"
