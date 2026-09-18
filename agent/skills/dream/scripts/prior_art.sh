#!/usr/bin/env bash
# Surface PRIOR ART for the notes written today, as a checklist demanding an outcome.
#
# WHY THIS EXISTS. On 2026-09-18 I verified a bug and wrote "the false-positive rate is
# unmeasured". It was measured, by me, on 2026-09-12: listing flicker at "at least 1 in 5".
# The number was in my own dreamer summary and I never looked, because `notes <term>` only
# fires if I remember to run it. Seven nights of retrospective say the same thing: an
# artifact that needs remembering fails, and a CHECKLIST that demands an outcome works
# (carry_forward.sh). So this does not ask me to search. It searches, and hands me lines I
# have to answer.
#
# It runs at dream time, which catches a miss within 24h rather than at write time. That is
# late, but it is RELIABLE, and reliable-and-late beats ideal-and-skipped.
set -uo pipefail

AGENT="${AGENT_HOME:-$HOME/agent}"
DAYS="${1:-1}"
since=$(date -u -d "${DAYS} days ago" +%Y-%m-%d 2>/dev/null || date -u +%Y-%m-%d)
today=$(date -u +%Y-%m-%d)

# Files changed recently that are NOTES/deep-dive prose, not code.
mapfile -t touched < <(
  find "$AGENT/skills" "$AGENT/deep-dives" -maxdepth 2 \
       \( -name 'NOTES-*.md' -o -name '*.md' -path '*deep-dives*' \) \
       -newermt "$since" -type f 2>/dev/null | sort
)

if [ "${#touched[@]}" -eq 0 ]; then
  echo "PRIOR ART: no NOTES or deep-dive files touched since ${since}. Nothing to cross-check."
  exit 0
fi

# Pull the headings added today. These are the claims worth cross-checking; body prose is
# too noisy to key on.
tmp=$(mktemp); trap 'rm -f "$tmp"' EXIT
for f in "${touched[@]}"; do
  grep -an "^## ${today}\|^## 2026-" "$f" 2>/dev/null \
    | tail -6 | sed "s|^|${f}:|" >> "$tmp"
done

if [ ! -s "$tmp" ]; then
  echo "PRIOR ART: files touched but no dated '## ' headings found since ${since}."
  exit 0
fi

echo "PRIOR ART CROSS-CHECK. For every match below, answer in tonight's summary:"
echo "  LINKED (pointer added) | GENUINELY NEW (prior art is about something else) | NOT RELEVANT"
echo "A match left unmentioned means the retrieval gap stayed open another night."
echo

# Stores that `recall` cannot see, i.e. exactly where I lose things.
TOPN="${TOPN:-3}"   # how many of the RAREST terms per entry to report
stores=("$AGENT/dreamer" "$AGENT/deep-dives" "$AGENT/skills" "$HOME/.contacts")

while IFS= read -r line; do
  file="${line%%:*}"
  rest="${line#*:}"; lno="${rest%%:*}"; heading="${rest#*:}"

  # Terms come from the heading AND the entry body, because a heading alone is too thin.
  body=$(sed -n "${lno},$((lno+25))p" "$file" 2>/dev/null)

  # IDENTIFIER-SHAPED ONLY: prose locates nothing. Earlier versions matched "question",
  # "animals", "arguing" in every file, and a term that hits everywhere points nowhere.
  cands=$(printf '%s\n%s\n' "$heading" "$body" \
    | grep -oE '[A-Za-z_][A-Za-z0-9_]{4,}' \
    | grep -E '_|[A-Z]{3,}' \
    | grep -viE '^(NOTES|MEMORY|VERIFIED|SHIPPED|https?)$' \
    | sort -u | head -30)

  # RANK BY RARITY, NEVER TAKE THE FIRST N. A positional cap lets ALLCAPS tokens (which sort
  # first in the C locale) eat every slot, so the term that actually locates the prior art is
  # never reached. A useful pointer need not be rare in absolute terms, only the rarest thing
  # in THIS entry.
  scored=""
  for t in $cands; do
    nfiles=$(grep -rails --include='*.md' -- "$t" "${stores[@]}" 2>/dev/null | wc -l)
    [ "$nfiles" -lt 2 ] && continue          # nothing to point at
    scored="${scored}${nfiles} ${t}\n"
  done

  hits=""
  for pair in $(printf "%b" "$scored" | sort -n | head -"$TOPN" | tr ' ' ':'); do
    [ -z "$pair" ] && continue
    nfiles="${pair%%:*}"; t="${pair#*:}"
    found=$(grep -rains --include='*.md' -- "$t" "${stores[@]}" 2>/dev/null \
            | grep -v "^${file}:" | head -3)
    [ -n "$found" ] && hits="${hits}    term '${t}' (in ${nfiles} files):\n${found}\n"
  done

  if [ -n "$hits" ]; then
    echo "  [ ] $(basename "$file"): ${heading:0:88}"
    printf "%b" "$hits" | sed 's/^/  /'
    echo
  fi
done < "$tmp"
