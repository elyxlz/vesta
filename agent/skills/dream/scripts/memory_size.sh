#!/bin/sh
file="$HOME/vesta/MEMORY.md"
chars=$(wc -c < "$file")
limit=12000
pct=$((chars * 100 / limit))
echo "${chars}/${limit} chars (${pct}%)"
