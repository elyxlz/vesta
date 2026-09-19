#!/usr/bin/env bash
# Print last dream's STILL OPEN list as a checklist tonight's summary must answer.
#
# WHY THIS EXISTS. The dream skill already requires that every item on the previous night's open
# list gets an explicit outcome. That rule was skipped on 2026-09-13 and again on 2026-09-15, and
# an audit of six nights found the leak correlates exactly with skipping it: eleven tracked items
# left the register by going unmentioned rather than by being closed. One of them was the item
# created to stop items leaking. A rule a reader can skip needs to become a list a reader is handed.
#
# FAILS LOUD BY DESIGN. Every abnormal path prints a RED line and exits non-zero. A carry-forward
# probe that printed nothing on a parse failure would read as "no open items", which is the exact
# false-reassurance this is meant to prevent.
set -uo pipefail

DREAMER_DIR="${DREAMER_DIR:-$HOME/agent/dreamer}"

if [ ! -d "$DREAMER_DIR" ]; then
    echo "RED carry-forward: no dreamer directory at $DREAMER_DIR"
    exit 1
fi

# The newest summary is the previous night's, because tonight's is written at the END of the dream.
# If tonight's already exists (a re-run), skip it so the list is still the one needing outcomes.
TODAY="$(date -u +%Y-%m-%d)"
prev=""
while IFS= read -r f; do
    case "$(basename "$f")" in
        "$TODAY"T*) continue ;;
    esac
    prev="$f"
    break
done < <(ls -1 "$DREAMER_DIR"/*.md 2>/dev/null | sort -r)

if [ -z "$prev" ]; then
    echo "RED carry-forward: no previous dreamer summary found in $DREAMER_DIR"
    exit 1
fi

# Section runs from the STILL OPEN heading to the next same-level heading.
section="$(awk '
    tolower($0) ~ /^## +(still open|unresolved|open (items|threads))/ { grab = 1; next }
    grab && /^## / { exit }
    grab { print }
' "$prev")"

if [ -z "$section" ]; then
    echo "RED carry-forward: $(basename "$prev") has no open-items section."
    echo "    Looked for a '## STILL OPEN' heading (also accepted: Unresolved, Open items,"
    echo "    Open threads). The canonical spelling is '## STILL OPEN'; see the dream skill."
    echo "    Either the previous dream skipped it, or the heading changed. Read the file before"
    echo "    assuming there is nothing to carry: an absent section is not an empty list."
    exit 1
fi

# One line per numbered item: the number plus the first line of its text.
# An item is a numbered line OR a bullet. The canonical form is numbered (see the dream skill),
# but a night that wrote bullets still has a real open list, and refusing to parse it would hand
# tonight NOTHING, which is the precise false reassurance this script exists to prevent.
items="$(printf '%s\n' "$section" | awk '
    /^[ \t]*([0-9]+\.|[-*+])[ \t]+/ {
        line = $0
        sub(/^[ \t]+/, "", line)
        print line
    }
')"

if [ -z "$items" ]; then
    echo "RED carry-forward: found a STILL OPEN section in $(basename "$prev") but no numbered items."
    echo "    The list may be prose. Read it by hand; do not record this as nothing to carry."
    exit 1
fi

count="$(printf '%s\n' "$items" | grep -c .)"
echo "CARRY FORWARD from $(basename "$prev"): $count open item(s)."
echo "Give EVERY line below an outcome in tonight's summary: fixed, blocked on <named thing>, or"
echo "dropped for <named reason>. An item must never leave the register by going unmentioned."
echo
printf '%s\n' "$items" | sed 's/^/  [ ] /' | cut -c1-160
exit 0
