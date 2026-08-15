#!/bin/sh
file="$HOME/agent/MEMORY.md"
# -m (characters), not -c (bytes): the cap is a character budget and this line calls its output
# "chars". A MEMORY.md holding accents, non-Latin text or emoji is multiple bytes per character, so
# -c silently overstates usage and the agent trims a file that was never near the limit. LC_ALL is
# set explicitly because `wc -m` counts bytes under the C locale; where C.UTF-8 is unavailable this
# degrades to the previous byte count rather than failing.
chars=$(LC_ALL=C.UTF-8 wc -m < "$file")
limit=50000
pct=$((chars * 100 / limit))
echo "${chars}/${limit} chars (${pct}%)"
