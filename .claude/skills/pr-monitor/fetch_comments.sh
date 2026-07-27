#!/usr/bin/env bash
# Emit comments on open PRs that address the bot, as TSV:
#   kind<TAB>id<TAB>pr<TAB>author<TAB>assoc<TAB>url<TAB>eyes<TAB>denied
# kind is issue (PR conversation), review (inline), or reviewbody (review summary).
# assoc is the commenter's author_association, which decides who may drive the
# agent. eyes and denied are the 👀 and 😕 reaction counts, both dedup signals.
# Every field comes from the list payload inside jq, so neither the trigger match
# nor either reaction count costs an extra API call.
set -uo pipefail

REPO="${REPO:?REPO is required (owner/name)}"
TRIGGER="${PR_MONITOR_TRIGGER:-@vestabot}"

valid() { grep -E "^(issue|review|reviewbody)$(printf '\t')"; }

# Must address the bot, and must not be one of our own comments. Our replies name
# the trigger when telling a reader how to reach us, and they are posted by an
# account that is also a trusted human, so nothing about the author distinguishes
# them: only the marker does. Every comment the agent posts carries it.
MARKER="${PR_MONITOR_MARKER:-vestabot:reply}"
G='select(.body != null) | select(.body | test("'"$TRIGGER"'"; "i")) | select(.body | contains("'"$MARKER"'") | not) | select((.body|ascii_downcase|contains("generated with")) and (.body|ascii_downcase|contains("claude code")) | not)'

prs=$(gh pr list --repo "$REPO" --state open --json number -q '.[].number' 2>/dev/null)
for pr in $prs; do
  gh api "/repos/$REPO/issues/$pr/comments" --paginate \
    -q '.[] | '"$G"' | "issue\t\(.id)\t'"$pr"'\t\(.user.login)\t\(.author_association)\t\(.html_url)\t\(.reactions.eyes)\t\(.reactions.confused)"' 2>/dev/null | valid || true
  gh api "/repos/$REPO/pulls/$pr/comments" --paginate \
    -q '.[] | '"$G"' | "review\t\(.id)\t'"$pr"'\t\(.user.login)\t\(.author_association)\t\(.html_url)\t\(.reactions.eyes)\t\(.reactions.confused)"' 2>/dev/null | valid || true
  gh api "/repos/$REPO/pulls/$pr/reviews" --paginate \
    -q '.[] | select(.body != "") | '"$G"' | "reviewbody\t\(.id)\t'"$pr"'\t\(.user.login)\t\(.author_association)\t\(.html_url)\t0\t0"' 2>/dev/null | valid || true
done
