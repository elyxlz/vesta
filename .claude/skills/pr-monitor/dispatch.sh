#!/usr/bin/env bash
# Drive one Claude session per PR from the monitor's event stream.
# Usage: dispatch.sh [owner/repo ...]
#
# Each PR keeps a single conversation: the session id from a PR's first event is
# stored and resumed for every later event on that PR, so the agent remembers
# what it already pushed and tried there. Context is not shared across PRs.
#
# Events on different PRs run concurrently, up to PARALLEL. Events on one PR do
# not: they resume that PR's session, and two runs resuming the same session
# would interleave writes to one conversation, so a per-PR lock keeps them in
# single file. The 👀 is claimed here, when the event is picked up, and a failed
# run releases it so the event surfaces again. The monitor re-emits anything
# still unclaimed, so the same event can arrive more than once and the claim is
# what makes handling it exactly once.
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR="$SKILL_DIR/monitor.sh"
MODEL="${PR_MONITOR_MODEL:-claude-opus-5}"
RUN_TIMEOUT="${PR_MONITOR_TIMEOUT:-1800}"
PARALLEL="${PR_MONITOR_PARALLEL:-3}"
STATE_ROOT="${PR_MONITOR_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/pr-monitor}"
ME="$(gh api /user -q .login 2>/dev/null)"

repos=("$@")
if [ "${#repos[@]}" -eq 0 ]; then
  repos=("$(gh repo view --json nameWithOwner -q .nameWithOwner)")
fi

# Standing context for every comment event. Without it the agent only does what
# the comment literally asked, so the depth of a review depended on whether the
# commenter happened to name a skill.
ROLE="<role>
You are this repository's pull request reviewer. You run unattended and reply on the PR, and maintainers read your reply instead of opening the diff themselves, so be the review they would otherwise have done.
</role>

<review_every_pr>
Do all of this on every pull request, whatever the comment asks for:

1. Find the issue it claims to fix. The PR body carries a closing keyword such as 'fixes #N'. Read that issue and decide whether this change actually resolves it, rather than whether the code merely looks reasonable. Say plainly when it fixes part of the issue, something adjacent to it, or nothing. If no issue is linked, say what problem you understand the PR to be solving and whether it is worth carrying.
2. Judge it against this repository's own rules, not generic taste. CLAUDE.md governs architecture, conventions, and style; the language sections cover the code it touches; a skill covering that area governs too. Test expectations and the repo-wide lint bans are in scope.
3. Never speculate about code you have not opened. Read the code paths the change touches and confirm the claims in its description and comments actually hold. Run something when running it settles the question.

Report what you find even when nobody asked for a review.
</review_every_pr>

<comment_length>
Engineers read your comment, not markers. It is a bug list and a verdict, not an essay: one line per finding, giving file:line, what breaks, and what triggers it. 80 words is a normal length and past 150 you are padding. Never narrate your review, never list what you checked that turned out fine, never restate the PR description.
</comment_length>

<this_run_is_your_only_turn>
You are one run. It ends the moment you stop producing output, and nothing resumes it: there is no later in which to post, check back, or follow up. Post your comment before you finish, always, even when something is still unresolved.

Never defer the comment to wait for CI, a build, a check, or anything else. Waiting is not something you can do. If something is still pending, say what is pending in the comment and give the verdict as NOT YET, so the reader knows what to look at when it settles.
</this_run_is_your_only_turn>

<signing_every_comment>
End every comment you post on a PR or issue with this exact line, alone on the last line:

<!-- vestabot:reply -->

It renders as nothing, and it is how the loop that woke you recognises its own writing. You post under an account that also belongs to a human maintainer, and your comments name the trigger when they tell a reader how to reach you, so without that marker your own comment reads as a fresh request and wakes you again on the next poll. Never put the marker on anything you did not write, and never omit it from anything you did.
</signing_every_comment>"

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

# Take the event, or report that somebody already has it. The monitor re-emits
# whatever it has not seen claimed, so this is what keeps a repeated event from
# being handled twice, and claiming here rather than at emit time is what keeps
# an event that was never picked up from being lost.
claim() {
  local repo="$1" kind="$2" id="$3" base ledger
  if [ "$kind" = "reviewbody" ]; then
    ledger="$STATE_ROOT/${repo//\//__}/seen_reviewbody.txt"
    mkdir -p "$(dirname "$ledger")"
    touch "$ledger"
    grep -qx "$id" "$ledger" 2>/dev/null && return 1
    echo "$id" >> "$ledger"
    return 0
  fi
  case "$kind" in
    issue)  base="/repos/$repo/issues/comments/$id/reactions" ;;
    review) base="/repos/$repo/pulls/comments/$id/reactions" ;;
    pr)     base="/repos/$repo/issues/$id/reactions" ;;
    *) return 1 ;;
  esac
  gh api "$base" -q '.[] | select(.content=="eyes") | .user.login' 2>/dev/null | grep -qxF "$ME" && return 1
  gh api -X POST "$base" -f content=eyes >/dev/null 2>&1
}

handle() {
  local repo="$1" kind="$2" id="$3" pr="$4" prompt="$5"
  local sf sid out rc lock
  lock="$STATE_ROOT/${repo//\//__}/locks"
  mkdir -p "$lock"
  exec 9>"$lock/pr-$pr.lock"
  # Another run holds this PR. Leave the event unclaimed so it comes back rather
  # than queueing behind that run and resuming its session underneath it.
  if ! flock -n 9; then
    return 0
  fi
  if ! claim "$repo" "$kind" "$id"; then
    return 0
  fi
  sf="$(session_file "$repo" "$pr")"
  local before
  before=$(gh api "/repos/$repo/issues/$pr/comments" -q 'length' 2>/dev/null)
  local args=(-p --model "$MODEL" --output-format json --dangerously-skip-permissions)
  [ -s "$sf" ] && args+=(--resume "$(cat "$sf")")
  # Events are handled one at a time, so a run that hangs holds every later event
  # behind it for as long as it lives, and a lost connection leaves one waiting on
  # a socket that never speaks again. The cap turns that into an ordinary failure.
  out=$(timeout "$RUN_TIMEOUT" claude "${args[@]}" "$prompt" 2>/dev/null)
  rc=$?
  # A stored id that no longer resolves would fail every retry, so forget it.
  if [ "$rc" -ne 0 ]; then
    [ "$rc" = "124" ] && echo "dispatch: run on $repo#$pr exceeded ${RUN_TIMEOUT}s and was stopped" >&2
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
  # A run that posts nothing looks identical to a healthy one from out here, and
  # the reason is usually that the model deferred the comment to a later it does
  # not get, so say so rather than reporting success.
  if [ "$(gh api "/repos/$repo/issues/$pr/comments" -q 'length' 2>/dev/null)" = "$before" ]; then
    echo "dispatch: WARN $repo#$pr run finished without commenting" >&2
  fi
  echo "dispatch: handled $repo#$pr ($kind $id)" >&2
  prune_sessions "$repo"
}

for repo in "${repos[@]}"; do prune_sessions "$repo"; done

bash "$MONITOR" "${repos[@]}" | while IFS=$'\t' read -r tag f1 f2 f3 f4 f5; do
  while [ "$(jobs -rp | wc -l)" -ge "$PARALLEL" ]; do wait -n; done
  case "$tag" in
    HIT)
      handle "$f1" "$f2" "$f3" "$f4" "$ROLE

<event>A developer addressed you in a comment on $f1 PR #$f4: $f5</event>
Read that comment and the pull request, do what it asks, then reply on the PR covering both the review above and what you changed. If its checks need fixing, use the babysit-prs skill. If the request is unclear or you decide not to act, say so in a reply rather than staying silent.
Only maintainers reach you here, so an explicit instruction outranks the repository's usual conventions: if the comment asks for something a skill or CLAUDE.md normally discourages, such as a force push or a rebase, do it and note it in your reply.
End every reply with a line starting 'Verdict:' giving your own call on merging: MERGE, DO NOT MERGE, or NOT YET, then one sentence of reasoning. Judge the change on its merits, not on whether you were the one who touched it, and say DO NOT MERGE when you believe that even if the commenter clearly wants it in. Never merge or close the PR yourself: the verdict is advice and the decision stays with the maintainer." &
      ;;
    NEWPR)
      handle "$f1" pr "$f2" "$f2" "$ROLE

<event>A pull request was opened on $f1: PR #$f2: $f3</event>
Nobody has asked for anything yet: this is the automatic check every new PR gets. Run the check-pr skill on it, then post your findings as a comment.
Stay read only. Do not push a commit, merge, close, or edit the PR. If it would benefit from the simplify and tidy pass, say so in one line and name the polish-pr skill so a maintainer can ask for it, but never run polish-pr yourself here." &
      ;;
    DEPPR)
      handle "$f1" pr "$f2" "$f2" "<event>A new dependabot pull request is open: $f1 PR #$f2: $f3</event>
Review it against this repository's dependency policy, check whether its checks pass, and act accordingly. Leave a comment recording what you decided.
Nobody asked for this, so close the comment with a couple of lines under a '---' rule saying how to ask for the next thing: mentioning @vestabot in a comment on the PR reaches you, what is worth asking for here, and that only maintainers can trigger you. The marker line goes last, after that.
End that comment with a line starting 'Verdict:' giving your own call on merging: MERGE, DO NOT MERGE, or NOT YET, then one sentence of reasoning. Never merge or close the PR yourself: the verdict is advice and the decision stays with the maintainer." &
      ;;
    *) [ -n "${tag:-}" ] && echo "dispatch: ignoring line: $tag" >&2 ;;
  esac
done
