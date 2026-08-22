#!/bin/sh
# scrub-check.sh -- would this text identify the user if it were published?
#
# Anything sent to the upstream repo (PR body, issue, review comment) is public, and every instance
# files that work on behalf of one identifiable private person. The gate for it is prose in a
# SKILL.md, and prose is read at the moment you are pleased with the sentence you just wrote, which
# is the moment the concrete example gets typed: the concrete case is always the persuasive one.
#
# So this is the gate as a command. It reads a file (or stdin) and reports every identifier it
# finds. Detection only, it never edits: a false positive on a common word must not silently
# rewrite an argument.
#
# Identifiers are resolved at run time from this instance's own environment and contacts store,
# never from a list committed to the repo, since such a list would publish the very names it
# exists to keep private.
#
# Usage: scrub-check.sh <file>        or  ... | scrub-check.sh
# Exit 0 clean, 1 if identifiers were found, 2 if nothing could be checked.

set -u

AGENT_DIR="${AGENT_DIR:-$HOME/agent}"

SRC="${1:--}"
if [ "$SRC" = "-" ]; then
    tmp=$(mktemp) || exit 2
    cat > "$tmp"
    SRC="$tmp"
    trap 'rm -f "$tmp"' EXIT
elif [ ! -f "$SRC" ]; then
    printf 'FAIL %s is not a readable file, so nothing was checked. This is not a clean result.\n' "$SRC" >&2
    exit 2
fi

hits=0
report() {
    hits=$((hits + 1))
    printf 'HIT  %-22s %s\n' "$1" "$2"
}

# Names. The owner plus everyone in the contacts store, since a contact's name identifies the user
# by association just as well as their own does. A hyphenated slug is split on the hyphen and each
# part tested on its own, so a two-part surname is caught when only half of it appears.
names=$(
    printf '%s\n' "${VESTA_OWNER:-}"
    [ -d "$HOME/.contacts" ] && {
        basename -s .md "$HOME"/.contacts/*.md 2>/dev/null
        sed -n 's/^# //p' "$HOME"/.contacts/*.md 2>/dev/null
    }
    sed -n 's/^- \*\*Name\*\*: *//p' "$AGENT_DIR/MEMORY.md" 2>/dev/null
)

# Counted, because zero names checked and zero names found print the same reassuring line.
checked=0
for n in $(printf '%s\n' "$names" | tr ',-' '\n\n' | tr -d '*[]' | tr 'A-Z' 'a-z' | sort -u); do
    # Two characters or fewer matches everything. "goes" and "by" come from the Name line's prose,
    # and "unknown" is the identity placeholder a box carries until it learns whose it is.
    [ "${#n}" -le 2 ] && continue
    case "$n" in goes|by|the|and|his|her|their|unknown) continue ;; esac
    checked=$((checked + 1))
    # -F: a slug is a literal, and a bracketed one would otherwise read as a character class.
    if grep -qiwF -- "$n" "$SRC" 2>/dev/null; then
        report "name" "$n"
    fi
done

# Contact-shaped strings. Kept high confidence on purpose: a bare digit run matches every line
# number and issue reference in a technical comment, so only international-format numbers count.
grep -qE '\+[0-9]{9,15}' "$SRC" && report "phone" "international-format number"
grep -qE '[0-9]{10,15}@(s\.whatsapp\.net|lid|c\.us)' "$SRC" && report "jid" "whatsapp jid"
# Boilerplate senders are not the owner, and the hook excludes them, so the two must agree: a
# noreply address in a quoted code block would otherwise fail the script and pass the hook.
grep -oiE '[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}' "$SRC" 2>/dev/null |
    grep -qivE '^(noreply|no-reply|example)' && report "email" "email address"
grep -qE 'https?://[^ ]*(ashbyhq|hibob|survey|invite)[^ ]*' "$SRC" && report "link" "personal onboarding or survey link"

if [ "$hits" -gt 0 ]; then
    printf '\n%s identifier(s) found. Genericize each before publishing.\n' "$hits"
    printf 'A hit is NOT automatically fatal: a name can be a false positive on a common word.\n'
    printf 'Judge each, but never publish one you have not looked at.\n'
    exit 1
fi

# No name resolved means the name half compared the text against nothing. Say so instead of
# passing, because a scrubber that knows no identifiers clears every text ever handed to it.
if [ "$checked" -eq 0 ]; then
    printf 'FAIL no name resolved from $VESTA_OWNER, %s or %s/.contacts,\n' "$AGENT_DIR/MEMORY.md" "$HOME" >&2
    printf 'so the name check compared against nothing. Contact-shaped strings and link patterns\n' >&2
    printf 'were checked and were clean. This is NOT a clean result for names.\n' >&2
    exit 2
fi

printf 'no identifiers found (%s name(s) checked). NOTE: names, contact-shaped strings and known\n' "$checked"
printf 'link patterns only, so a paraphrase that identifies the user by circumstance will not appear.\n'
exit 0
