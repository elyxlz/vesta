#!/usr/bin/env bash
# Drive one Claude session per PR from the monitor's event stream.
# Usage: dispatch.sh [owner/repo ...]
#
# Each PR keeps a single conversation: the session id from a PR's first event is
# stored and resumed for every later event on that PR, so the agent remembers
# what it already pushed and tried there. Context is not shared across PRs.
#
# Events are handled serially, so a burst cannot start overlapping runs against
# the same session. The 👀 monitor.sh posts is a claim rather than a completion:
# a failed run releases it, and the event surfaces again on the next cycle.
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR="$SKILL_DIR/monitor.sh"
MODEL="${PR_MONITOR_MODEL:-claude-opus-5}"
STATE_ROOT="${PR_MONITOR_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/pr-monitor}"
ME="$(gh api /user -q .login 2>/dev/null)"

repos=("$@")
if [ "${#repos[@]}" -eq 0 ]; then
  repos=("$(gh repo view --json nameWithOwner -q .nameWithOwner)")
fi

session_file() {
  local dir="$STATE_ROOT/${1//\//__}/sessions"
  mkdir -p "$dir"
  printf '%s/pr-%s.session' "$dir" "$2"
}

# Drop our own 👀 so a failed event is retried. Another account's reaction on the
# same comment is left alone.
release() {
  local repo="$1" kind="$2" id="$3" base rid ledger
  if [ "$kind" = "reviewbody" ]; then
    ledger="$STATE_ROOT/${repo//\//__}/seen_reviewbody.txt"
    if [ -f "$ledger" ]; then
      grep -vx "$id" "$ledger" > "$ledger.tmp" || true
      mv "$ledger.tmp" "$ledger"
    fi
    return 0
  fi
  case "$kind" in
    issue)  base="/repos/$repo/issues/comments/$id/reactions" ;;
    review) base="/repos/$repo/pulls/comments/$id/reactions" ;;
    pr)     base="/repos/$repo/issues/$id/reactions" ;;
    *) return 1 ;;
  esac
  rid=$(gh api "$base" -q '.[] | select(.content=="eyes") | select(.user.login=="'"$ME"'") | .id' 2>/dev/null | head -1)
  [ -n "$rid" ] || return 0
  gh api -X DELETE "$base/$rid" >/dev/null 2>&1
}

remove_transcript() {
  [ -n "${1:-}" ] || return 0
  find "$HOME/.claude/projects" -name "$1.jsonl" -delete 2>/dev/null || true
}

# A PR's session is resumed only while the PR is open, so once it closes the
# pointer is dead weight and its transcript is never read again. Transcripts are
# the part that grows without bound, so removing them is opt-in rather than
# silent. A failed listing returns early: an empty one legitimately means every
# PR closed, but an errored one must never be read as "prune everything".
prune_sessions() {
  local repo="$1" dir open file pr
  dir="$STATE_ROOT/${repo//\//__}/sessions"
  [ -d "$dir" ] || return 0
  open=$(gh pr list --repo "$repo" --state open --limit 200 --json number -q '.[].number' 2>/dev/null) || return 0
  for file in "$dir"/pr-*.session; do
    [ -e "$file" ] || continue
    pr="${file##*/pr-}"
    pr="${pr%.session}"
    printf '%s\n' "$open" | grep -qx "$pr" && continue
    [ "${PR_MONITOR_PRUNE_TRANSCRIPTS:-0}" = "1" ] && remove_transcript "$(cat "$file")"
    rm -f "$file"
    echo "dispatch: pruned session for closed $repo#$pr" >&2
  done
}

handle() {
  local repo="$1" kind="$2" id="$3" pr="$4" prompt="$5"
  local sf sid out rc
  sf="$(session_file "$repo" "$pr")"
  local args=(-p --model "$MODEL" --output-format json --dangerously-skip-permissions)
  [ -s "$sf" ] && args+=(--resume "$(cat "$sf")")
  out=$(claude "${args[@]}" "$prompt" 2>/dev/null)
  rc=$?
  # A stored id that no longer resolves would fail every retry, so forget it.
  if [ "$rc" -ne 0 ]; then
    echo "dispatch: claude failed rc=$rc on $repo#$pr, releasing claim" >&2
    [ -s "$sf" ] && rm -f "$sf"
    release "$repo" "$kind" "$id"
    return 1
  fi
  sid=$(printf '%s' "$out" | jq -r '.session_id // empty' 2>/dev/null)
  [ -n "$sid" ] && printf '%s' "$sid" > "$sf"
  if [ "$(printf '%s' "$out" | jq -r '.is_error // false' 2>/dev/null)" = "true" ]; then
    echo "dispatch: claude reported an error on $repo#$pr, releasing claim" >&2
    release "$repo" "$kind" "$id"
    return 1
  fi
  echo "dispatch: handled $repo#$pr ($kind $id)" >&2
  prune_sessions "$repo"
}

for repo in "${repos[@]}"; do prune_sessions "$repo"; done

bash "$MONITOR" "${repos[@]}" | while IFS=$'\t' read -r tag f1 f2 f3 f4 f5; do
  case "$tag" in
    HIT)
      handle "$f1" "$f2" "$f3" "$f4" "A developer addressed you in a comment on $f1 PR #$f4: $f5
Read that comment and the pull request, do what it asks, then reply on the PR describing what you changed. If its checks need fixing, use the babysit-prs skill. If the request is unclear or you decide not to act, say so in a reply rather than staying silent.
Only maintainers reach you here, so an explicit instruction outranks the repository's usual conventions: if the comment asks for something a skill or CLAUDE.md normally discourages, such as a force push or a rebase, do it and note it in your reply.
End every reply with a line starting 'Verdict:' giving your own call on merging: MERGE, DO NOT MERGE, or NOT YET, then one sentence of reasoning. Judge the change on its merits, not on whether you were the one who touched it, and say DO NOT MERGE when you believe that even if the commenter clearly wants it in. Never merge or close the PR yourself: the verdict is advice and the decision stays with the maintainer."
      ;;
    DEPPR)
      handle "$f1" pr "$f2" "$f2" "A new dependabot pull request is open: $f1 PR #$f2: $f3
Review it against this repository's dependency policy, check whether its checks pass, and act accordingly. Leave a comment recording what you decided.
End that comment with a line starting 'Verdict:' giving your own call on merging: MERGE, DO NOT MERGE, or NOT YET, then one sentence of reasoning. Never merge or close the PR yourself: the verdict is advice and the decision stays with the maintainer."
      ;;
    *) [ -n "${tag:-}" ] && echo "dispatch: ignoring line: $tag" >&2 ;;
  esac
done
