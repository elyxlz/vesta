#!/bin/sh
file="$HOME/agent/MEMORY.md"
chars=$(wc -c < "$file")
limit=50000
pct=$((chars * 100 / limit))
echo "${chars}/${limit} chars (${pct}%)"
