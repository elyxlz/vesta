#!/bin/sh
# gate2b-check.sh -- does this diff ship the story instead of the mechanism?
#
# Gate 2b of upstream-pr/SKILL.md: anything under `agent/` never describes a previous design,
# because the agent reads it cold and a description of the old system reads as a description of the
# current one. The gate names five things to cut from the diff: the superseded wording, the date,
# the box or version it was found on, the incident behind it, and any narration of what the code
# did before. The exact wording lives in upstream-pr/SKILL.md; it is paraphrased here so this file
# passes its own check, which is a property worth having in a linter.
#
# The gate is a rule asking an agent to remember, which is the weakest artifact available: it is
# read at the moment you are pleased with a sentence you just wrote, and it is your own prose you
# are being asked to judge. This runs it instead.
#
# Scope is deliberately narrow: ADDED lines only, under agent/, in comments and markdown prose.
# Usage:  gate2b-check.sh [<git-diff-args>...]        default: staged + unstaged vs HEAD
# Exit 0 clean, 1 findings printed, 2 could not run.

set -u

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    printf 'FAIL gate2b-check: not a git repository, so the diff was NOT checked.\n' >&2
    exit 2
fi

# The caller may scope with `--`, as git does. Args stay in the positional list rather than being
# re-joined into a string, so nothing needs word splitting and quoting survives. When the caller
# supplied no pathspec, add ours; when they did, theirs wins and the awk below still refuses to
# report anything outside agent/, so the scope holds either way.
#
# git's stderr is kept, not discarded: a mistyped rev produces an empty diff, and an empty diff
# reported as "nothing to judge" is the exact shape that reads as a clean bill of health forever.
[ "$#" -gt 0 ] || set -- HEAD
has_sep=0
for a in "$@"; do
    [ "$a" = "--" ] && has_sep=1
done

diff_err=$(mktemp)
if [ "$has_sep" -eq 1 ]; then
    diff_out=$(git diff "$@" 2>"$diff_err")
else
    diff_out=$(git diff "$@" -- 'agent/*' 2>"$diff_err")
fi
rc=$?
if [ "$rc" -ne 0 ]; then
    printf 'FAIL gate2b-check: git diff exited %s, so the diff was NOT checked.\n' "$rc" >&2
    cat "$diff_err" >&2
    rm -f "$diff_err"
    exit 2
fi
rm -f "$diff_err"

# A file git has never seen has no diff, so a brand-new SKILL.md sailed through this check
# entirely: every line of it is an added line and none of them was being read. Found by the
# "nothing was judged" wording below, which is the whole reason that wording exists rather than a
# cheerful "clean". Synthesize the added-line form for untracked files instead of mutating the
# index with `git add -N`, because a lint must not change what the next commit would contain.
if [ "$has_sep" -eq 0 ] && [ "$1" = "HEAD" ] && [ "$#" -eq 1 ]; then
    untracked=$(git ls-files --others --exclude-standard -- 'agent/*' 2>/dev/null)
    for f in $untracked; do
        [ -f "$f" ] || continue
        diff_out="$diff_out
+++ b/$f"
        diff_out="$diff_out
$(sed 's/^/+/' "$f")"
    done
fi

# An empty diff is not a pass, it is nothing to judge. Say which, because "no findings" against an
# empty input is the exact shape that reads as a clean bill of health forever.
if [ -z "$diff_out" ]; then
    echo "gate2b-check: no added lines under agent/ in this diff, so nothing was judged."
    exit 0
fi

printf '%s\n' "$diff_out" | awk '
/^\+\+\+ /            { file = substr($0, 7); next }
!/^\+/                { next }
/^\+\+\+/             { next }
{
    line = substr($0, 2)
    probe = tolower(line)

    # Only prose: a comment, a markdown line, or a docstring. Code that happens to contain a
    # numeral pair is not narration and flagging it would train me to ignore this.
    if (file !~ /^agent\//) next

    is_prose = (probe ~ /^[ \t]*#/) || (probe ~ /^[ \t]*\/\//) || (file ~ /\.md$/) || (probe ~ /^[ \t]*\*/)
    if (!is_prose) next

    # MEMORY.md is the only exemption. Gate 2b protects files that ship to other instances, which
    # read them cold with no history. MEMORY is the history of one box, is never upstreamed, and is
    # deliberately written as dated findings. Flagging it would be noise, and a lint with noise in
    # it is one you learn to skim, which is the same as not having it.
    if (file ~ /MEMORY\.md$/) next

    # A date that is a QUOTED FLAG VALUE or a BACKTICKED format example is data, not narration.
    # `--at "2026-12-01T08:00:00"` and `SINCE="2026-08-17T08:00:00"` teach a reader the format they
    # must type; they do not say when anything was observed. Gate 2b cuts the date that dates the
    # incident, so keying on the date alone needs this one carve-out or the check flags the
    # documentation it has no business rewriting, and a lint with noise in it is one you skim.
    is_example = (probe ~ /["=`]20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)

    why = ""
    # No \b anywhere below. mawk supports {n,m} intervals but NOT word boundaries, and silently
    # never matches a pattern containing one, so a rule written with \b leaves the script looking
    # like it ran while being unable to refuse. Keep every pattern boundary-free.
    if (probe ~ /previously|used to|formerly|the old (default|value|wording|version|behaviour|behavior)/)
        why = "narrates the previous design"
    else if (probe ~ /[0-9]+,[ ]*not[ ]+[0-9]+/)
        why = "narrates the previous default (\"X, not Y\")"
    # A BARE date is the violation. Gate 2b says "cut from the diff: ... the date ..." with no
    # qualifier, so requiring a nearby verb (observed, found, broke) would key on the examples that
    # happen to prompt the rule rather than on the rule, and every dated sentence phrased another
    # way would pass. Generalise from the rule, never from its examples.
    else if (probe ~ /[0-9][0-9]?[ ]+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*([^a-z]|$)/ ||
             probe ~ /(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[ ]+[0-9][0-9]?([^0-9]|$)/ ||
             (probe ~ /20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ && !is_example))
        why = "carries a date, which gate 2b cuts from the diff regardless of how it is phrased"
    else if (probe ~ /this (used to|would|was) (be|say|return|do)|before this (change|fix|pr)/)
        why = "describes the system before the change"

    if (why != "") {
        printf "GATE2B  %s\n", file
        printf "GATE2B    %s\n", why
        printf "GATE2B    %s\n", line
        hits++
    }
}
END {
    if (hits) {
        printf "GATE2B  %d line(s). Gate 2b: the diff carries the mechanism and the constraint only.\n", hits
        printf "GATE2B  The story is not deleted, it MOVES: put it in the commit message and the PR\n"
        printf "GATE2B  body, where a reviewer wants it anyway. Litmus: read the added prose as an\n"
        printf "GATE2B  agent who has never seen the bug, and cut every sentence that only makes\n"
        printf "GATE2B  sense if you have.\n"
        exit 1
    }
    print "gate2b-check: no narration of a prior design in the added prose under agent/."
}
'
