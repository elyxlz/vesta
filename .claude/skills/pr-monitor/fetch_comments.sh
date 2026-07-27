#!/usr/bin/env bash
# Emit comments on open PRs that address the bot, as TSV:
#   kind<TAB>id<TAB>pr<TAB>author<TAB>url<TAB>eyes
# kind is issue (PR conversation), review (inline), or reviewbody (review summary).
# Both filters and the reaction count are read from the list payload inside jq,
# so neither the trigger match nor the dedup signal costs an extra API call.
set -uo pipefail

REPO="${REPO:?REPO is required (owner/name)}"
TRIGGER="${PR_MONITOR_TRIGGER:-@vestabot}"

valid() { grep -E "^(issue|review|reviewbody)$(printf '\t')"; }

# Must address the bot, and must not be one of our own replies, which quote the
# developer's text and would otherwise re-trigger on their own mention.
G='select(.body != null) | select(.body | test("'"$TRIGGER"'"; "i")) | select((.body|ascii_downcase|contains("generated with")) and (.body|ascii_downcase|contains("claude code")) | not)'

prs=$(gh pr list --repo "$REPO" --state open --json number -q '.[].number' 2>/dev/null)
for pr in $prs; do
  gh api "/repos/$REPO/issues/$pr/comments" --paginate \
    -q '.[] | '"$G"' | "issue\t\(.id)\t'"$pr"'\t\(.user.login)\t\(.html_url)\t\(.reactions.eyes)"' 2>/dev/null | valid || true
  gh api "/repos/$REPO/pulls/$pr/comments" --paginate \
    -q '.[] | '"$G"' | "review\t\(.id)\t'"$pr"'\t\(.user.login)\t\(.html_url)\t\(.reactions.eyes)"' 2>/dev/null | valid || true
  gh api "/repos/$REPO/pulls/$pr/reviews" --paginate \
    -q '.[] | select(.body != "") | '"$G"' | "reviewbody\t\(.id)\t'"$pr"'\t\(.user.login)\t\(.html_url)\t0"' 2>/dev/null | valid || true
done
