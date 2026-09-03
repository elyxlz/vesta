#!/bin/sh
file="$HOME/agent/MEMORY.md"
# The cap is a character budget: -m counts characters, and bare `wc -m` counts bytes under the C locale.
chars=$(LC_ALL=C.UTF-8 wc -m < "$file")
limit=50000
pct=$((chars * 100 / limit))
echo "${chars}/${limit} chars (${pct}%)"
