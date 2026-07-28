#!/usr/bin/env bash
# Persistent PR event source. Anyone can comment on a public repo, so only a
# trusted commenter can drive the agent: see PR_MONITOR_TRUSTED and is_trusted.
# An untrusted comment gets a 😕 rather than silence, so the person sees it was
# read and refused, and the loop does not reconsider it every cycle.
#
# Loops forever, printing one line per new event:
#   HIT    <repo> <kind> <id> <pr> <url>   a developer comment addressing the bot
#   NEWPR  <repo> <pr> <url>               a newly seen open PR, for its first check
#   DEPPR  <repo> <pr> <url>               a newly seen open dependabot PR
# Usage: monitor.sh [owner/repo ...]   (defaults to the current repo)
#
# Dedup is a 👀 reaction on the comment or PR itself, not a local ledger, so the
# state lives on GitHub and survives losing the working directory. The consumer
# posts it when it picks the event up, never this loop: an event claimed here but
# never consumed, because the consumer was busy or restarted, would be lost with
# no way to notice. Unclaimed events are simply re-emitted next cycle, so the
# consumer must tolerate seeing one more than once.
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FETCH="$SKILL_DIR/fetch_comments.sh"
INTERVAL="${PR_MONITOR_INTERVAL:-45}"
TRUSTED="${PR_MONITOR_TRUSTED:-}"
DENIED_REACTION="${PR_MONITOR_DENIED_REACTION:-confused}"
STATE_ROOT="${PR_MONITOR_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/pr-monitor}"

repos=("$@")
if [ "${#repos[@]}" -eq 0 ]; then
  repos=("$(gh repo view --json nameWithOwner -q .nameWithOwner)")
fi

state_dir() {
  local dir="$STATE_ROOT/${1//\//__}"
  mkdir -p "$dir"
  printf '%s' "$dir"
}

# Post a reaction. Non-zero means it was not recorded, so callers stay silent
# rather than emit an event they cannot mark as handled.
react() {
  local repo="$1" kind="$2" id="$3" content="$4"
  case "$kind" in
    issue)  gh api -X POST "/repos/$repo/issues/comments/$id/reactions" -f content="$content" >/dev/null 2>&1 ;;
    review) gh api -X POST "/repos/$repo/pulls/comments/$id/reactions"  -f content="$content" >/dev/null 2>&1 ;;
    pr)     gh api -X POST "/repos/$repo/issues/$id/reactions"          -f content="$content" >/dev/null 2>&1 ;;
    *) return 1 ;;
  esac
}

# Anyone who can comment on a public repo can reach this loop, so only trusted
# commenters may drive the agent. An explicit login list wins when set;
# otherwise trust is inherited from the commenter's repository role.
is_trusted() {
  local login="$1" assoc="$2"
  if [ -n "$TRUSTED" ]; then
    printf '%s' "$TRUSTED" | tr ',' ' ' | tr -s ' ' '\n' | grep -qxF "$login"
    return
  fi
  case "$assoc" in OWNER | MEMBER | COLLABORATOR) return 0 ;; *) return 1 ;; esac
}

emit_comments() {
  local repo="$1" dir tsv ledger
  dir="$(state_dir "$repo")"
  tsv="$dir/addressed.tsv"
  ledger="$dir/seen_reviewbody.txt"
  touch "$ledger"
  REPO="$repo" bash "$FETCH" > "$tsv" 2>/dev/null || true
  # An empty fetch is normal: it means nobody has addressed the bot.
  [ -s "$tsv" ] || return 0
  if grep -qvE "^(issue|review|reviewbody)$(printf '\t')" "$tsv" 2>/dev/null; then
    echo "WARN: malformed fetch for $repo, skipping cycle" >&2
    return 0
  fi
  local kind id pr author assoc url eyes denied
  while IFS=$'\t' read -r kind id pr author assoc url eyes denied; do
    [ -z "${id:-}" ] && continue
    # Bots never trigger, even when they name the bot.
    case "$author" in *'[bot]') continue ;; esac

    # Review summaries have no reactions endpoint anywhere in the GitHub API,
    # so this one kind keeps a local ledger and cannot signal a refusal.
    if [ "$kind" = "reviewbody" ]; then
      grep -qx "$id" "$ledger" 2>/dev/null && continue
      if is_trusted "$author" "$assoc"; then
        printf 'HIT\t%s\t%s\t%s\t%s\t%s\n' "$repo" "$kind" "$id" "$pr" "$url"
      else
        echo "monitor: ignoring $repo#$pr review from untrusted $author" >&2
        echo "$id" >> "$ledger"
      fi
      continue
    fi

    # Either reaction means this comment already got an answer.
    [ "${eyes:-0}" != "0" ] && continue
    [ "${denied:-0}" != "0" ] && continue

    # An untrusted commenter gets a visible refusal rather than silence, which
    # also stops the comment being reconsidered on every later cycle.
    if ! is_trusted "$author" "$assoc"; then
      react "$repo" "$kind" "$id" "$DENIED_REACTION"
      echo "monitor: refused $repo#$pr comment $id from untrusted $author ($assoc)" >&2
      continue
    fi

    printf 'HIT\t%s\t%s\t%s\t%s\t%s\n' "$repo" "$kind" "$id" "$pr" "$url"
  done < "$tsv"
}

# Open PRs surface once each, on sight, without needing the trigger: dependabot
# ones as DEPPR, everything else as NEWPR. Drafts are skipped. A 👀 on the PR
# itself is the record that it was seen, and reactionGroups rides along in the
# same listing, so the check costs nothing extra.
emit_open_prs() {
  local repo="$1"
  gh pr list --repo "$repo" --state open --limit 200 --json number,headRefName,url,isDraft,reactionGroups \
    -q '.[] | select(.isDraft | not) | select((([.reactionGroups[]? | select(.content=="EYES") | .users.totalCount] | add) // 0) == 0) | "\(if (.headRefName|startswith("dependabot/")) then "DEPPR" else "NEWPR" end)\t\(.number)\t\(.url)"' 2>/dev/null | \
  while IFS=$'\t' read -r kind num url; do
    [ -z "${num:-}" ] && continue
    printf '%s\t%s\t%s\t%s\n' "$kind" "$repo" "$num" "$url"
  done
}

# One poller per repo, so a slow repo never delays another, and the interval is
# measured from the start of a pass rather than its end, so the time a pass
# takes is not added to the gap before the next one. Both matter because how
# soon an event is noticed is what decides whether two of them can ever be in
# flight together: discovery a cycle apart is handled a cycle apart, however
# many runs the consumer is willing to start at once.
# Each line is written whole and stays under the pipe's atomic write size, so
# pollers writing at the same time cannot interleave a line.
poll_repo() {
  local repo="$1" started elapsed
  while true; do
    started=$(date +%s)
    emit_comments "$repo"
    emit_open_prs "$repo"
    elapsed=$(( $(date +%s) - started ))
    [ "$elapsed" -lt "$INTERVAL" ] && sleep "$(( INTERVAL - elapsed ))"
  done
}

for repo in "${repos[@]}"; do
  poll_repo "$repo" &
done
wait
