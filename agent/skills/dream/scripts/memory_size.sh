#!/bin/sh
# MEMORY.md size, total and per-section. The total says how close to the cap the file is but never
# where the mass sits, so a curation pass has to guess which section to cut and can nibble the wrong
# one for several passes while the real offender grows. Read the biggest number first: a section
# over ~20% of the file is the one to split, moving its detail out and leaving a pointer behind.
file="$HOME/agent/MEMORY.md"
chars=$(wc -c < "$file")
limit=30000
pct=$((chars * 100 / limit))
echo "${chars}/${limit} chars (${pct}%)"

echo ""
echo "by section (biggest first; >20% of total means split it):"
awk -v total="$chars" '
  /^## / || /^### / {
    if (name != "") sizes[name] = len
    name = $0; len = 0
  }
  { len += length($0) + 1 }
  END {
    if (name != "") sizes[name] = len
    for (n in sizes) printf "%7d  %5.1f%%  %s\n", sizes[n], 100 * sizes[n] / total, n
  }
' "$file" | sort -rn | head -12
