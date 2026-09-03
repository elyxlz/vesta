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
RUN_TIMEOUT="${PR_MONITOR_TIMEOUT:-7200}"
PARALLEL="${PR_MONITOR_PARALLEL:-3}"
PRUNE_WORKTREES_EVERY="${PR_MONITOR_PRUNE_WORKTREES:-3600}"
BACKOFF_MIN="${PR_MONITOR_BACKOFF_MIN:-60}"
BACKOFF_MAX="${PR_MONITOR_BACKOFF_MAX:-1800}"
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

<comment_shape>
The comment answers one question for a maintainer who has not opened the diff: is this noise, is it bugged, or is it worth merging. No opening line: the first characters are the first label. Write every label every time, in this order, and write none under one that is empty rather than dropping it.

Fixes: the linked issue and whether this closes it, fully or partly or not at all.
Blocking: findings that should stop the merge, two lines each. First line: file:line, what the code does, what goes wrong. Second line, starting Proof:, the command and what it printed, or the input that triggers it, or the two places that contradict each other.
Non-blocking: everything else worth saying, same two lines.
Verdict: NOISE if the change should not be carried at all, BUGGED if it is worth having but wrong as written, MERGE if you attacked it and it held, then the one thing that decided it.

Judge the diff and nothing else. CI is not your business: it is on the PR page already and says nothing about whether the change is right.

Proof a reader cannot check is worth nothing: never write verified locally, I audited this, tests pass, or looks correct. Where you could not settle a finding, write Proof: none, read only. 150 words is the ceiling. Never narrate the review, never list what you checked that turned out fine, never restate the PR description.
</comment_shape>

<this_run_is_your_only_turn>
You are one run. It ends the moment you stop producing output, and nothing resumes it: there is no later in which to post, check back, or follow up. Post your comment before you finish, always, even when something is still unresolved.

Never defer the comment to wait for CI, a build, a check, or anything else. Waiting is not something you can do. Say what is still pending on the CI line so the reader knows what to look at when it settles, and still give one of the three verdicts on what you can see now.
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
  local repo="$1" dir open file pr wtroot
  dir="$STATE_ROOT/${repo//\//__}/sessions"
  [ -d "$dir" ] || return 0
  open=$(gh pr list --repo "$repo" --state open --limit 200 --json number -q '.[].number' 2>/dev/null) || return 0
  wtroot="$(cd "$(git -C "$SKILL_DIR" rev-parse --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd)"
  for file in "$dir"/pr-*.session; do
    [ -e "$file" ] || continue
    pr="${file##*/pr-}"
    pr="${pr%.session}"
    printf '%s\n' "$open" | grep -qx "$pr" && continue
    [ "${PR_MONITOR_PRUNE_TRANSCRIPTS:-0}" = "1" ] && remove_transcript "$(cat "$file")"
    rm -f "$file"
    # The PR's review worktree dies with its session: it is a disposable read
    # surface reset from master each run, so nothing in it is ever worth keeping.
    [ -n "$wtroot" ] && git -C "$wtroot" worktree remove --force "$wtroot/.claude/worktrees/pr-review-$pr" 2>/dev/null
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

# Subagents that fan out get a worktree each, and the harness keeps any that
# carries commits so work is never silently deleted, so they accumulate one per
# run forever. A worktree is removed here only once its work is provably safe to
# lose: its PR is merged or closed, or its commits are already on master by
# content. Anything with uncommitted changes is left alone, and `git worktree
# remove` without --force refuses a dirty tree anyway, so a race cannot delete
# work that appeared after the check.
prune_worktrees() {
  local repo="$1" root marker wt branch head state
  root="$(cd "$(git rev-parse --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd)/.claude/worktrees"
  [ -d "$root" ] || return 0
  marker="$STATE_ROOT/last-worktree-prune"
  if [ -f "$marker" ] && [ "$(( $(date +%s) - $(stat -c %Y "$marker") ))" -lt "$PRUNE_WORKTREES_EVERY" ]; then
    return 0
  fi
  mkdir -p "$STATE_ROOT"; touch "$marker"
  local closed
  closed=$(gh pr list --repo "$repo" --state closed --limit 400 --json headRefName -q '.[].headRefName' 2>/dev/null) || return 0
  git fetch -q origin 2>/dev/null || true
  for wt in "$root"/*/; do
    [ -d "$wt" ] || continue
    # Review worktrees are always clean and at master, so this sweep would yank
    # one from under a live run; their lifecycle is prune_sessions', on PR close.
    case "$wt" in */pr-review-*) continue ;; esac
    [ -n "$(git -C "$wt" status --porcelain 2>/dev/null | head -1)" ] && continue
    head=$(git -C "$wt" rev-parse HEAD 2>/dev/null) || continue
    state=keep
    branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null)
    if [ -n "$branch" ] && printf '%s\n' "$closed" | grep -qxF "$branch"; then
      state=merged
    elif [ -z "$(git -C "$wt" cherry origin/master "$head" 2>/dev/null | grep '^+')" ]; then
      state=landed
    fi
    [ "$state" = keep ] && continue
    if git -C "$root" worktree remove "$wt" 2>/dev/null || git -C "$wt" worktree remove "$wt" 2>/dev/null; then
      echo "dispatch: removed worktree $(basename "$wt") ($state)" >&2
    fi
  done
  git -C "$root" worktree prune 2>/dev/null || true
}

# A run's working directory is this checkout, so a stray `gh pr checkout` in one
# moves the branch the dispatcher is executing from. Bash reads a running script
# by byte offset, so rewriting dispatch.sh underneath it misparses the rest, and
# a HEAD left on a PR branch quietly runs that branch's skills instead of the
# deployed ones. Restore only with no run in flight, since that is the one moment
# no agent is mid-checkout, and let `git checkout` refuse rather than discard
# changes it would overwrite.
restore_checkout() {
  [ -z "$(jobs -rp)" ] || return 0
  [ "$(git -C "$SKILL_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null)" = master ] && return 0
  if git -C "$SKILL_DIR" checkout master >/dev/null 2>&1; then
    echo "dispatch: restored checkout to master" >&2
  else
    echo "dispatch: WARN checkout is off master and would not restore" >&2
  fi
}

# A 429 is the whole account going quiet, not this one event failing, so every
# other run is about to hit it too and retrying at the poll interval just burns
# the queue against a closed door. Hold the dispatcher instead, doubling the wait
# each time. Concurrent runs all fail against the same limit, so only the first
# one past the current window lengthens it.
rate_limited() {
  local now until secs
  now=$(date +%s)
  until=$(cat "$STATE_ROOT/backoff-until" 2>/dev/null || echo 0)
  [ "$now" -lt "$until" ] && return 0
  secs=$(cat "$STATE_ROOT/backoff" 2>/dev/null || echo 0)
  if [ "$secs" -le 0 ]; then secs="$BACKOFF_MIN"; else secs=$(( secs * 2 )); fi
  [ "$secs" -gt "$BACKOFF_MAX" ] && secs="$BACKOFF_MAX"
  mkdir -p "$STATE_ROOT"
  printf '%s' "$secs" > "$STATE_ROOT/backoff"
  printf '%s' "$(( now + secs ))" > "$STATE_ROOT/backoff-until"
  echo "dispatch: rate limited by the API, holding ${secs}s before the next run" >&2
}

# The first run that gets through says the limit has lifted, so start the next
# one over at the shortest wait rather than wherever the last streak ended.
clear_backoff() {
  rm -f "$STATE_ROOT/backoff" "$STATE_ROOT/backoff-until"
}

await_backoff() {
  local until now
  until=$(cat "$STATE_ROOT/backoff-until" 2>/dev/null) || return 0
  now=$(date +%s)
  [ "$now" -ge "$until" ] && return 0
  sleep "$(( until - now ))"
}

# A run launched in the dispatcher's own tree reads the deployed snapshot, which
# can lag origin/master by releases and cite deleted code as current (#2175).
# Give each PR a disposable worktree reset to just-fetched master instead: plain
# reads resolve to today's code, the path is stable so the PR's resumed session
# keeps its footing, and the dispatcher's checkout is never rewritten under the
# running script. Only the repo this checkout tracks gets one; a foreign repo
# has no local tree, and any failure falls back to the old working directory.
review_worktree() {
  local repo="$1" pr="$2" root wt
  root="$(cd "$(git -C "$SKILL_DIR" rev-parse --git-common-dir 2>/dev/null)/.." 2>/dev/null && pwd)" || return 1
  git -C "$root" remote get-url origin 2>/dev/null | grep -qF "$repo" || return 1
  git -C "$root" fetch -q origin master >/dev/null 2>&1 || return 1
  wt="$root/.claude/worktrees/pr-review-$pr"
  if [ -d "$wt" ]; then
    git -C "$wt" checkout -q --detach origin/master >/dev/null 2>&1 || return 1
    git -C "$wt" reset -q --hard origin/master >/dev/null 2>&1 || return 1
  else
    git -C "$root" worktree add -q --detach "$wt" origin/master >/dev/null 2>&1 || return 1
  fi
  printf '%s' "$wt"
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
  # Every path out of a claimed run has to give the claim back, and being killed
  # is one of them: systemd signals the whole service, so a deploy lands here
  # mid-run. Without this the claim survives with nothing running behind it, the
  # monitor reads it as handled, and the event is never emitted again.
  trap 'release "$repo" "$kind" "$id"; exit 143' TERM INT
  sf="$(session_file "$repo" "$pr")"
  local before wt
  wt="$(review_worktree "$repo" "$pr")" || wt=""
  before=$(gh api "/repos/$repo/issues/$pr/comments" -q 'length' 2>/dev/null)
  local args=(-p --model "$MODEL" --output-format json --dangerously-skip-permissions)
  [ -s "$sf" ] && args+=(--resume "$(cat "$sf")")
  # The cap exists to end a run that has stopped making progress, not a slow one:
  # a lost connection leaves a run waiting on a socket that never speaks again,
  # consuming no CPU and looking alive. It must sit well above how long real work
  # takes, because a run killed after it has pushed leaves the commit with nothing
  # explaining it, and the retry repeats the work. A polish pass dispatches a
  # blocking subagent and runs past half an hour; an abandoned run sat for twelve.
  out=$( { [ -z "$wt" ] || cd "$wt" || exit 9; } && timeout "$RUN_TIMEOUT" claude "${args[@]}" "$prompt" 2>/dev/null )
  rc=$?
  # A stored id that no longer resolves would fail every retry, so forget it.
  if [ "$rc" -ne 0 ]; then
    # Running out of quota says nothing about this PR or its session, so keep the
    # conversation and hold the dispatcher rather than dropping both.
    if [ "$(printf '%s' "$out" | jq -r '.api_error_status // empty' 2>/dev/null)" = "429" ]; then
      rate_limited
      release "$repo" "$kind" "$id"
      trap - TERM INT
      return 1
    fi
    [ "$rc" = "124" ] && echo "dispatch: run on $repo#$pr exceeded ${RUN_TIMEOUT}s and was stopped" >&2
    echo "dispatch: claude failed rc=$rc on $repo#$pr, releasing claim" >&2
    [ -s "$sf" ] && rm -f "$sf"
    release "$repo" "$kind" "$id"
    trap - TERM INT
    return 1
  fi
  sid=$(printf '%s' "$out" | jq -r '.session_id // empty' 2>/dev/null)
  [ -n "$sid" ] && printf '%s' "$sid" > "$sf"
  if [ "$(printf '%s' "$out" | jq -r '.is_error // false' 2>/dev/null)" = "true" ]; then
    echo "dispatch: claude reported an error on $repo#$pr, releasing claim" >&2
    release "$repo" "$kind" "$id"
    trap - TERM INT
    return 1
  fi
  # A run that posts nothing looks identical to a healthy one from out here, and
  # the reason is usually that the model deferred the comment to a later it does
  # not get, so say so rather than reporting success.
  if [ "$(gh api "/repos/$repo/issues/$pr/comments" -q 'length' 2>/dev/null)" = "$before" ]; then
    echo "dispatch: WARN $repo#$pr run finished without commenting" >&2
  fi
  trap - TERM INT
  clear_backoff
  echo "dispatch: handled $repo#$pr ($kind $id)" >&2
  prune_sessions "$repo"
  prune_worktrees "$repo"
}

restore_checkout
for repo in "${repos[@]}"; do prune_sessions "$repo"; prune_worktrees "$repo"; done

bash "$MONITOR" "${repos[@]}" | while IFS=$'\t' read -r tag f1 f2 f3 f4 f5; do
  while [ "$(jobs -rp | wc -l)" -ge "$PARALLEL" ]; do wait -n; done
  await_backoff
  restore_checkout
  case "$tag" in
    HIT)
      handle "$f1" "$f2" "$f3" "$f4" "$ROLE

<event>A developer addressed you in a comment on $f1 PR #$f4: $f5</event>
Read that comment and the pull request, do what it asks, then reply on the PR covering both the review above and what you changed. If its checks need fixing, use the babysit-prs skill. If the request is unclear or you decide not to act, say so in a reply rather than staying silent.
Only maintainers reach you here, so an explicit instruction outranks the repository's usual conventions: if the comment asks for something a skill or CLAUDE.md normally discourages, such as a force push or a rebase, do it and note it in your reply.
End every reply with a line starting 'Verdict:' giving your own call: NOISE if the change should not be carried at all, BUGGED if it is worth having but wrong as written, MERGE if you attacked it and it held, then one sentence of reasoning. Judge the change on its merits, not on whether you were the one who touched it, and say NOISE or BUGGED when you believe it even if the commenter clearly wants it in. Never merge or close the PR yourself: the verdict is advice and the decision stays with the maintainer." &
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
End that comment with a line starting 'Verdict:' giving your own call: NOISE, BUGGED, or MERGE, then one sentence of reasoning. Never merge or close the PR yourself: the verdict is advice and the decision stays with the maintainer." &
      ;;
    *) [ -n "${tag:-}" ] && echo "dispatch: ignoring line: $tag" >&2 ;;
  esac
done
