---
name: issues-to-prs
description: >
  Use when the user asks to turn issues into PRs, work through the backlog, pick
  the easiest issues and fix them, "issues to prs", or "grab the top N issues and
  PR them". Ranks open issues by tractability, shows the shortlist for approval,
  then fans out one worktree-isolated subagent per approved issue to open a PR,
  and automatically follows each PR with a code review plus a trimming pass.
  Works on the current repo unless the user names another.
---

# Issues to PRs

Backlog to mergeable PRs in one pass: rank, approve, build, review, report.

Two phases, both automatic after the approval gate. **Phase 1** opens a PR per issue. **Phase 2** reviews and trims each PR. Never skip phase 2, and never fold it into phase 1: an agent told to review its own work before the PR exists stops on the review and strands uncommitted work.

## Workflow

1. **Gather candidates.**
   ```
   gh issue list --state open --limit 100 --json number,title,labels,createdAt
   gh pr list --state open --limit 100 --json number,title,headRefName,body
   ```

2. **Filter hard before ranking.** Read each candidate's full body (`gh issue view <N>`). Drop it if any of:

   | Condition | Why |
   | --- | --- |
   | An open PR already targets it | Grep PR bodies for `#<N>`. Expect this to catch several. |
   | The issue says it needs the owner's call | "needs the maintainer", "pick one", "decide", two lettered options |
   | It is a pure strategy, legal, or pricing question | Not implementable, no correct answer without the user |
   | It is blocked on upstream or an external event | Nothing to land today |
   | It names a fleet-floor or version gate not yet met | Premature, and dangerous |

   Do **not** drop an issue for being wrong. A wrong diagnosis is still a real bug report (see Hard rules).

3. **Rank by tractability**, cheapest first: blast radius (one file beats one subsystem), whether a test can prove it, whether the fix is named in the issue, whether it touches fleet state (a migration makes it harder), and whether CI can verify it (Docker or live gated is harder).

4. **Show the shortlist and get approval.** Present the top N (default 10, or the user's number) with a one-line "what this is" and a one-line "why it is easy" each. Use `AskUserQuestion` with `multiSelect: true` so the user picks a subset. Also list what you filtered out and why, grouped, in one or two lines per group. That list is often the most useful part: it tells the user what is actually blocked on them.

   If fewer than N survive the filter, **say so and stop at the real number**. Never pad the list with decision-gated issues to hit N. Two real candidates beats ten with eight duds.

5. **Warn once, before dispatch:** ask the user not to merge these PRs until phase 2 reports. Merging mid-flight closes the branch, so a trim that lands afterwards goes nowhere and needs re-targeting as a fresh PR. Say it once, do not nag.

6. **Phase 1: one subagent per approved issue.** Dispatch all in a single message so they run in parallel:
   `Agent({ subagent_type: "general-purpose", isolation: "worktree", ... })`.
   Build each prompt from the "Phase 1 prompt" section below.

7. **Verify each PR yourself.** Do not report from the agent's own summary. For each:
   ```
   gh pr view <N> --json mergeable,mergeStateStatus,statusCheckRollup
   ```
   Green means `merge-gate-ci` concluded `SUCCESS` with zero `FAILURE`/`TIMED_OUT`. A finished agent that says "green" may be reporting a stale head: check the head SHA is the one it pushed.

8. **Phase 2: one review subagent per PR**, again in one message. Build each from the "Phase 2 prompt" section below.

9. **Final report.** Per PR: number, issue, net LOC delta from the trim, real bugs the review found, and CI state. Then, separately and prominently:
   - **Bugs the review found in the batch's own work.** These matter more than the trim.
   - **Anything an agent refused to do, and why.** A refusal is usually a finding.
   - **Anything an agent did NOT verify.** Carry it forward verbatim; do not launder it into a claim.
   - Follow-up issues opened for out-of-scope findings.

## Phase 1 prompt (one PR per issue)

Include verbatim in each subagent prompt:

- Repo, issue number, and: **read the issue in full first** (`gh issue view <N>`).
- Setup: `git fetch origin && git checkout -b <type>/<slug> origin/master`.
- Isolation: stay in your worktree for the whole task, never `cd` to the shared checkout, other agents are running in parallel.
- **The issue's diagnosis is a hypothesis, not a spec.** Verify the stated root cause against the real code before implementing. If it is wrong, fix the real cause and say so in the PR body. If the bug is already fixed, say that and do not manufacture a diff.
- **Order is load-bearing: implement, verify, commit, push, open the PR. Only then review anything.**
- Checks: the relevant `./check.sh` subcommands must pass. Write output to a log file whose name includes the issue number: parallel agents share one scratchpad and collide on default log names. Never pipe checks through `tail`/`head` in a way that masks the exit code.
- PR body must contain `Fixes #<N>`. Use `Refs #<N>` instead when landing only part of an issue, so it stays open.
- Then poll until `merge-gate-ci` concludes. The PR must end green.
- Report: PR URL, one line on the change, what you did **not** verify, and the CI result.

Add per-issue, from the issue body: the fleet-impact question when it touches on-disk or config state, which of several suggested options to take and why, and any constraint that must not change.

## Phase 2 prompt (review and trim each PR)

Include verbatim:

- Target PR number and branch. Setup with a **distinct local branch name** (`git checkout -B review/<N> origin/<branch>`): the phase 1 worktree still holds that branch, and git refuses the same branch in two worktrees.
- Run `/code-review` at high effort over `git diff origin/master...HEAD`. Act on real findings.
- Then trim: cut comments, LOC, and fluff as hard as the repo's own rules already demand. Delete every comment that restates the code, narrates history, or explains the obvious. Keep only a comment stating a non-obvious constraint the code cannot show. Cut dead abstractions, single-use indirection, over-verbose tests, redundant assertions. Prose and copy: cut padding, say it once.
- **State what is NOT fluff.** This is the most important part of the prompt and it is per-PR. Name every load-bearing thing that merely looks decorative, and say why. Get this wrong and the trim breaks the fix.
- **Never trim coverage.** If the PR's tests were proven to discriminate (they fail against the bug), re-prove it on the new branch after trimming: apply the mutation, watch the test fail, revert. Verify, do not assume.
- Behavior must not change. No version bumps. No force-push, no history rewrite: commit on top.
- Push to the PR's branch, then poll until `merge-gate-ci` concludes green.
- **If the PR was merged or closed while you worked**, pushing to its branch lands nothing and CI will not run. Do not push into the void. Re-target onto `origin/master` as a new PR, re-verify every claim against master (do not trust a check you ran on the old branch), and reference the original PR. If the PR was closed rather than merged, stop and ask instead.
- Report: net LOC delta, what you cut, real bugs found, what you did not verify, final CI state.
- **A trim producing no changes is a valid outcome.** Say so and push nothing. Never manufacture a diff to look productive.

## Hard rules

- **Verify claims, never relay them.** An issue's diagnosis and a PR body's coverage claim are both assertions by someone with blind spots. Passing them on launders an assertion into a fact the user acts on. In one batch, three did not survive checking: an issue blamed an env var that was exported nowhere and whose removal would have made the bug worse, an issue was already fixed by a merged PR, and a PR body claimed two regression tests where only one was.
- **Prefer coverage proven by mutation.** "The test passes" means nothing. Revert the fix, watch the test fail, restore. A test that cannot fail is decoration.
- **Never pad the shortlist** to hit N.
- **Never let a subagent review before its PR exists.** It will stop on the review output and strand the work.
- **Never force-push, never amend, never rewrite** a pushed branch. Always a new commit.
- **Never bump versions.** `release.sh` owns that.
- **Never merge or close** anything. This skill opens PRs and reports.
- **Report refusals as findings.** An agent that declines the task and argues why is usually right, and it is the highest-signal output of the run. Surface the argument, do not bury it.
- **Never claim green from a local run.** Only a concluded `merge-gate-ci` counts, on the head you pushed.
- **Stop if `gh auth status` is unauthenticated.**

## Don'ts

- Don't fan out before the user approves. The approval gate is the point.
- Don't re-rank or re-litigate an issue the user deselected.
- Don't skip phase 2 because phase 1 was green. The review is where the real bugs surfaced: a live regression on master, a fleet regression that would have silently withheld new files for a release cycle, and a page that bounced its own target audience to a sign-in wall.
- Don't let phase 2 widen a PR's scope. Out-of-scope findings become issues, and say in the issue that it came from reviewing PR #N.
- Don't run both phases against a repo the user did not name.
