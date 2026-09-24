#!/usr/bin/env bash
# Surface PRIOR ART for the notes written today, as a checklist demanding an outcome.
#
# WHY THIS EXISTS. On 2026-09-17 I verified a bug and wrote that my evidence was "nowhere near
# a false-positive measurement". It was measured, by me, on 2026-09-12: flicker at "at least 1 in 5".
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
  #
  # THE ALLCAPS CLAUSE WAS THE SAME BUG WEARING A HAT, found on its first real run
  # (2026-09-19). The filter used to accept `_` OR three consecutive capitals, and my notes
  # use CAPS for emphasis on ordinary English, so it dutifully surfaced RISES, SHRINK,
  # ANYWAY, WORSE, MYSELF and CARRIED: prose readmitted through the clause written to keep
  # prose out. An identifier is now a token carrying an underscore or a digit, which is what
  # every term that has ever actually located prior art here looks like (`dead_at`,
  # `revived_at`, `_pgn`, `REVIVE_SHARE`). An entry of pure prose now yields NOTHING, and
  # that is the correct answer rather than the three rarest English words in it.
  cands=$(printf '%s\n%s\n' "$heading" "$body" \
    | grep -oE '[A-Za-z_][A-Za-z0-9_]{4,}' \
    | grep -E '_|[0-9]' \
    | grep -viE '^(NOTES|MEMORY|VERIFIED|SHIPPED|https?)$' \
    | sort -u | head -30)

  # RANK BY RARITY, NEVER TAKE THE FIRST N. A positional cap lets ALLCAPS tokens (which sort
  # first in the C locale) eat every slot, so the term that actually locates the prior art is
  # never reached. A useful pointer need not be rare in absolute terms, only the rarest thing
  # in THIS entry.
  # THE SAME FILE IS A STORE TOO. A notes file grows to thousands of lines, and an idea
  # re-derived far below its first statement is the commonest miss, so a term found nowhere
  # else still counts when it appears in this file ABOVE the oldest heading this run keys on.
  # The entry's own lines and anything after them are today's work and are excluded.
  cut=$(awk -F: -v f="$file" '$1==f {print $2}' "$tmp" | sort -n | head -1)
  scored=""
  for t in $cands; do
    nfiles=$(grep -rails --include='*.md' -- "$t" "${stores[@]}" 2>/dev/null | wc -l)
    other=$(( nfiles > 0 ? nfiles - 1 : 0 ))   # the term came from $file, so $file is one of them
    earlier=$(grep -an -- "$t" "$file" 2>/dev/null | awk -F: -v c="$cut" '$1 < c' | wc -l)
    [ "$other" -eq 0 ] && [ "$earlier" -eq 0 ] && continue   # nothing to point at
    places=$(( other + (earlier > 0 ? 1 : 0) ))
    scored="${scored}${places} ${t}\n"
  done

  hits=""
  for pair in $(printf "%b" "$scored" | sort -n | head -"$TOPN" | tr ' ' ':'); do
    [ -z "$pair" ] && continue
    places="${pair%%:*}"; t="${pair#*:}"
    found=$(grep -rains --include='*.md' -- "$t" "${stores[@]}" 2>/dev/null \
            | grep -v "^${file}:" | head -3)
    same=$(grep -an -- "$t" "$file" 2>/dev/null | awk -F: -v c="$cut" -v f="$file" '$1 < c {print f":"$0}' | tail -3)
    [ -n "$same" ] && found="${found:+$found
}${same}"
    [ -n "$found" ] && hits="${hits}    term '${t}' (in ${places} places, same-file lines above ${cut} count):\n${found}\n"
  done

  if [ -n "$hits" ]; then
    echo "  [ ] $(basename "$file"): ${heading:0:88}"
    printf "%b" "$hits" | sed 's/^/  /'
    echo
  fi
done < "$tmp"
