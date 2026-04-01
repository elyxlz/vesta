#!/bin/sh
file="$HOME/vesta/MEMORY.md"
chars=$(wc -c < "$file")
limit=16384
pct=$((chars * 100 / limit))
echo "${chars}/${limit} chars (${pct}%)"
