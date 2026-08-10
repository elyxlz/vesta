#!/bin/sh
# Scan the FILESYSTEM for credentials, which redact_secrets.sh does not do.
#
# redact_secrets.sh covers events.db and the channel stores, which is where a credential the USER
# pasted ends up. It cannot see files. But an agent writes credentials to files too: a token
# redirected into a file instead of a shell variable, a key material sidecar a tool left behind, a
# .env someone dropped in a project. Nothing in the nightly sweep looks there, so that whole class
# of leak is reported clean by a scan that never had the chance to see it.
#
# Detection only, deliberately. It prints candidates and never deletes: an agent's own working key
# material and a leaked copy look identical to a regex, so destroying the wrong one breaks a working
# integration. Judge each hit, then remove it yourself.
#
# Usage: scan_files_for_secrets.sh [roots], default `/tmp $HOME`.
# Exit 0 clean, 1 if candidates were found, 2 if the scan could not run.

ROOTS="${1:-/tmp $HOME}"

# Excluded because they are large, self-refreshing, and full of false positives: package caches,
# the git object store, and the message stores redact_secrets.sh already covers properly.
PRUNE='-name .git -o -name node_modules -o -name .cache -o -name .venv -o -name __pycache__ -o -name go -o -name .npm'

# High-confidence content signatures only. A generic "40 hex chars" rule matches every git sha on
# the box, so it is left out on purpose: a report nobody reads because it cries wolf is worse than
# no report.
SIGS='(ghp|ghs|gho|ghu|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9]{32,}|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|glpat-[A-Za-z0-9_-]{20,}'

# Names that are credential stores by convention, flagged whatever their content, because a
# passphrase or a human-chosen password matches no pattern at all.
# The secret and token forms are DOTFILES and EXTENSIONS, never bare substrings: `*secret*` and
# `*token*` match `tokenize.py`, `token.h`, `secrets.py` and `design-tokens.css`, and a report
# padded with the standard library is a report that gets skimmed, which is the same as not having
# one.
NAMES='-name *.pem -o -name *.key -o -name id_rsa* -o -name id_ed25519* -o -name .env -o -name .netrc -o -name .pgpass -o -name .npmrc -o -name *.tok -o -name credentials* -o -name .*secret* -o -name .*token* -o -name *.secret -o -name *.token'

# A root that does not exist must NOT read as a clean root: a scan that could not have found
# anything reporting "nothing found" is the same shape as the leak this script exists for, one
# level up, absence mistaken for evidence.
usable=0
for root in $ROOTS; do
    if [ -d "$root" ]; then
        usable=$((usable + 1))
    else
        printf 'SKIP %s does not exist, so it was NOT scanned\n' "$root" >&2
    fi
done
if [ "$usable" -eq 0 ]; then
    printf 'FAIL none of the given roots exist (%s), so nothing was scanned. This is not a clean result.\n' "$ROOTS" >&2
    exit 2
fi

for root in $ROOTS; do
    [ -d "$root" ] || continue

    # By name. Report the path and size, never the contents: printing a credential to solve a
    # credential leak is how the value ends up in the event store, which is the exact loop this
    # whole phase exists to break.
    find "$root" \( $PRUNE \) -prune -o -type f \( $NAMES \) -print 2>/dev/null | while read -r f; do
        printf 'HIT  %-52s %s bytes, by NAME\n' "$f" "$(wc -c < "$f" 2>/dev/null)"
    done

    # By content. Size-capped: a credential is short, and grepping multi-gigabyte model weights
    # buys nothing but minutes.
    find "$root" \( $PRUNE \) -prune -o -type f -size -256k -print 2>/dev/null | while read -r f; do
        if grep -qE "$SIGS" "$f" 2>/dev/null; then
            printf 'HIT  %-52s %s bytes, by CONTENT\n' "$f" "$(wc -c < "$f" 2>/dev/null)"
        fi
    done
done

# The subshells above cannot raise a counter in this shell, so recount from the same finds a reader
# would. Cheap, and it keeps the exit code honest rather than always zero.
total=$(
    for root in $ROOTS; do
        [ -d "$root" ] || continue
        find "$root" \( $PRUNE \) -prune -o -type f \( $NAMES \) -print 2>/dev/null
        find "$root" \( $PRUNE \) -prune -o -type f -size -256k -print 2>/dev/null |
            while read -r f; do grep -qE "$SIGS" "$f" 2>/dev/null && echo "$f"; done
    done | sort -u | wc -l
)

printf '\nscanned: %s\n' "$ROOTS"
if [ "$total" -gt 0 ]; then
    printf '%s candidate file(s). Judge each, then remove the real ones yourself (this script never deletes).\n' "$total"
    printf 'A file here is NOT automatically a leak: your own working key material looks the same.\n'
    exit 1
fi
printf 'no credential-shaped files found. NOTE: this checks names and high-confidence signatures\n'
printf 'only, so a human-chosen password in a plain text file will not appear here.\n'
exit 0
