#!/usr/bin/env bash
# Emit comments on open PRs that address the bot, as TSV:
#   kind<TAB>id<TAB>pr<TAB>author<TAB>assoc<TAB>url<TAB>eyes<TAB>denied
# kind is issue (PR conversation), review (inline), or reviewbody (review summary).
# assoc is the commenter's author_association, which decides who may drive the
# agent. eyes and denied are the 👀 and 😕 reaction counts, both dedup signals.
# Conversation and inline comments come from one repo-wide listing each, windowed
# by PR_MONITOR_WINDOW: a listing per open PR cost three calls per PR per cycle
# and grew with the backlog. Review summaries have no repo-wide listing.
set -uo pipefail

REPO="${REPO:?REPO is required (owner/name)}"
TRIGGER="${PR_MONITOR_TRIGGER:-@vestabot}"
WINDOW="${PR_MONITOR_WINDOW:-7 days ago}"

valid() { grep -E "^(issue|review|reviewbody)$(printf '\t')"; }

# Must address the bot, and must not be one of our own comments. Our replies name
# the trigger when telling a reader how to reach us, and they are posted by an
# account that is also a trusted human, so nothing about the author distinguishes
# them: only the marker does. Every comment the agent posts carries it.
MARKER="${PR_MONITOR_MARKER:-vestabot:reply}"
G='select(.body != null) | select(.body | test("'"$TRIGGER"'"; "i")) | select(.body | contains("'"$MARKER"'") | not) | select((.body|ascii_downcase|contains("generated with")) and (.body|ascii_downcase|contains("claude code")) | not)'

open_prs=$(mktemp) || exit 0
trap 'rm -f "$open_prs"' EXIT
gh pr list --repo "$REPO" --state open --limit 200 --json number -q '.[].number' 2>/dev/null > "$open_prs"
[ -s "$open_prs" ] || exit 0

since=$(date -u -d "$WINDOW" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null) || exit 0
[ -n "$since" ] || exit 0

# The repo-wide listings cover every PR and issue, so drop anything whose PR is
# not currently open: a comment on a closed PR is none of our business.
only_open() { awk -F'\t' 'NR==FNR{o[$1];next} ($3 in o)' "$open_prs" -; }

gh api "/repos/$REPO/issues/comments?since=$since&per_page=100" --paginate \
  -q '.[] | '"$G"' | "issue\t\(.id)\t\(.issue_url|split("/")|last)\t\(.user.login)\t\(.author_association)\t\(.html_url)\t\(.reactions.eyes)\t\(.reactions.confused)"' 2>/dev/null | valid | only_open || true

gh api "/repos/$REPO/pulls/comments?since=$since&per_page=100" --paginate \
  -q '.[] | '"$G"' | "review\t\(.id)\t\(.pull_request_url|split("/")|last)\t\(.user.login)\t\(.author_association)\t\(.html_url)\t\(.reactions.eyes)\t\(.reactions.confused)"' 2>/dev/null | valid | only_open || true

while read -r pr; do
  [ -n "$pr" ] || continue
  gh api "/repos/$REPO/pulls/$pr/reviews" --paginate \
    -q '.[] | select(.body != "") | '"$G"' | "reviewbody\t\(.id)\t'"$pr"'\t\(.user.login)\t\(.author_association)\t\(.html_url)\t0\t0"' 2>/dev/null | valid || true
done < "$open_prs"
