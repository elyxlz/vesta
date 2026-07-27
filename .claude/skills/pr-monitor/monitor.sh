#!/usr/bin/env bash
# Persistent PR event source. Anyone can comment on a public repo, so only a
# trusted commenter can drive the agent: see PR_MONITOR_TRUSTED and is_trusted.
# An untrusted comment gets a 😕 rather than silence, so the person sees it was
# read and refused, and the loop does not reconsider it every cycle.
#
# Loops forever, printing one line per new event:
#   HIT    <repo> <kind> <id> <pr> <url>   a developer comment addressing the bot
#   DEPPR  <repo> <pr> <url>               a newly seen open dependabot PR
# Usage: monitor.sh [owner/repo ...]   (defaults to the current repo)
#
# Dedup is a 👀 reaction placed on the comment or PR itself, not a local ledger,
# so the state lives on GitHub and survives losing the working directory. The 👀
# is posted here at emit time rather than by whatever consumes these lines, so an
# event cannot re-fire every cycle while it waits to be handled.
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

ack() { react "$1" "$2" "$3" eyes; }

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
      fi
      echo "$id" >> "$ledger"
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

    if ack "$repo" "$kind" "$id"; then
      printf 'HIT\t%s\t%s\t%s\t%s\t%s\n' "$repo" "$kind" "$id" "$pr" "$url"
    else
      echo "WARN: could not ack $repo $kind $id, not emitting" >&2
    fi
  done < "$tsv"
}

# Dependabot PRs deliberately bypass the trigger and surface on sight.
# reactionGroups rides along in the same listing, so the check costs nothing.
emit_dependabot() {
  local repo="$1"
  gh pr list --repo "$repo" --state open --json number,headRefName,url,reactionGroups \
    -q '.[] | select(.headRefName|startswith("dependabot/")) | select((([.reactionGroups[]? | select(.content=="EYES") | .users.totalCount] | add) // 0) == 0) | "\(.number)\t\(.url)"' 2>/dev/null | \
  while IFS=$'\t' read -r num url; do
    [ -z "${num:-}" ] && continue
    if ack "$repo" pr "$num"; then
      printf 'DEPPR\t%s\t%s\t%s\n' "$repo" "$num" "$url"
    else
      echo "WARN: could not ack dependabot PR $repo#$num, not emitting" >&2
    fi
  done
}

while true; do
  for repo in "${repos[@]}"; do
    emit_comments "$repo"
    emit_dependabot "$repo"
  done
  sleep "$INTERVAL"
done
