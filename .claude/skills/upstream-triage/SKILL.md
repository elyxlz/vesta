---
name: upstream-triage
description: >
  Use when the user asks to triage, review, or work through the PRs that vesta agents filed
  (author `app/vesta-upstream`), decide which are worth merging, find the clean fix behind a
  bandaid, consolidate PRs that touch the same file, or run "upstream-triage". Also for an
  epic branch that folded many agent PRs without review. Produces a decision report the
  maintainer walks through, then executes the decisions: merges, consolidated rewrites, and
  close comments that point each closed PR at its replacement.
---

# Upstream triage

Agents inside user containers file real problems with short-sighted fixes: a guard at the symptom, a second mechanism beside one master already has, new state where existing state already encodes the fact, a large script where a small one would do, one user's layout leaked into upstream. Their box is a stale snapshot and their context is user work, so the clean fix is hidden from them. The maintainer's checkout is where it is visible. This skill finds it, one PR at a time, and turns the agent's problem report into the right change.

Three phases. Phase 1 is automated and read-only. Phase 2 is a conversation with the maintainer. Phase 3 is automated again and writes to GitHub.

The report is the spine of all three: `~/vesta-triage/<date>-upstream-triage.md`, outside the repo so it cannot be committed. Write to it after every agent result and every decision, never in batches. Context gets summarized mid-run; the file is what survives.

## Phase 1: triage

**1. List and cluster.** `bash .claude/skills/upstream-triage/clusters.sh` prints every open `app/vesta-upstream` PR with its touched files, grouped so that PRs sharing a file land in one cluster. CI state is not a filter: agents wait for green before reporting a PR done, so nearly every PR is green and mergeable. Design quality is the only filter.

**2. One reviewer per cluster, in parallel.** For each cluster launch one `general-purpose` agent whose prompt is: follow `.claude/skills/check-pr/SKILL.md` in **report-only** mode for each PR in the cluster (its Clean-fix lens is what finds the hidden fix), then answer the cluster questions: do these PRs overlap or contradict each other, which one (if any) carries the right problem statement, and what is the one change that replaces the set. The agent returns each PR's check-pr comment text plus the cluster answer. Read-only: no comments, no branches, no worktrees.

For an epic branch that folded many closed PRs (a maintainer's `epic/*` branch), split by area instead of by PR and use `triage-fold-prompt.md` in this directory: each slice reads `git diff origin/master...origin/<epic>` for its paths plus the folded PRs' bodies, and judges each folded PR against current master.

**3. Write the report.** One row per PR in a summary table (PR, title, verdict, Decision `pending`), then one section per PR: Problem, Root cause and layer, Fix quality, Clean fix, Verdict, Confidence, `Decision: pending`. Map check-pr's verdicts to the maintainer's choices: `MERGE` stays; `MERGE` with non-blocking nits a maintainer can apply in ten minutes is `MERGE-WITH-NITS`; `NOISE` that names a clean fix is `REWRITE`; `NOISE` for a false premise, an already-fixed problem, a duplicate, or personal-workspace tooling is `CLOSE`; a product call the maintainer must make first is `HUMAN`. Record side findings that are not tied to one PR (a convention with no check, a pattern across many CLIs) in a list at the top.

## Phase 2: decide

Walk the report with the maintainer one PR (or one cluster) at a time. For each: the problem in one sentence, whether it is real, what the PR does, what the clean fix is, one recommendation, and the one question only the maintainer can answer if there is one. The maintainer answers; write the Decision line immediately, then move to the next. Do not present the whole report and ask for a verdict on everything.

Standing rules, so they are not re-litigated per PR:

- **Same file, one PR.** PRs that touch the same region of one file are closed together and replaced by one consolidated PR. Never merge one of a conflicting set and leave the rest to rebase.
- **The problem statement is kept, the fix is replaced.** A REWRITE credits the closed PR by number in the new PR's body. The agent's diagnosis and evidence were the valuable part.
- **An epic is rebuilt, not rebased.** When most of a fold is dropped, build the survivors fresh from master as a few single-concern PRs; surgery on a stale branch leaves the same review to do.
- **A false claim is recorded.** When a PR body claims tests or behavior the diff does not contain, the close comment says so in one neutral sentence, so the filing agent learns it.

## Phase 3: execute

Append an execution table to the report (item, sources, status) and keep it current. Then:

**Merge as-is** (squash, matching master's history) anything decided MERGE with green CI.

**Nits on the bot's branch**: one implementing agent per PR, following `implement-prompt.md` in this directory. The bot's branch is on the same repo, so a maintainer push lands on the existing PR. Merge when green.

**Fresh PRs** (REWRITE, consolidations, epic survivors): one implementing agent per PR, `implement-prompt.md`, the report section as its spec. Each works in its own worktree off `origin/master`, opens the PR with `Supersedes #N, #M.` as the body's last line, and reports when CI is green. Agents never merge or close anything. Cap the parallel wave at about eight; queue the rest.

**Central close pass**, once every replacement PR has a number: close each superseded PR and the epic with one comment naming the replacement (`Superseded by #<new>: <one line on what changed in the fix>. Thank you for the diagnosis.`). Agents read PR comments, so the comment is how the filing agent learns what happened. Merge the fresh PRs in dependency order (the report names the order when PRs touch one file).

**Close the linked issues too.** An agent files a PR and an issue as a pair, but a superseded PR is closed rather than merged, so its `Closes #N` never fires and the issue outlives the fix. So the backlog does not grow while PRs land: when a PR resolves an issue, close that issue in the same pass with a comment naming the PR that fixed it (a merged replacement) or the reason it will not be done (a `CLOSE` verdict). Find the linked issue in the superseded PR's body (`Closes #N` / `Fixes #N`) or by matching the problem. A fresh PR that itself carries `Closes #N` closes its issue on merge and needs no manual step.

## Files in this directory

- `clusters.sh`: open bot PRs with touched files, grouped by shared file.
- `triage-fold-prompt.md`: the slice prompt for an epic branch that folded many PRs.
- `implement-prompt.md`: the prompt every implementing agent follows in phase 3.

## Cost

One review agent per cluster is 50 to 120k tokens and 2 to 6 minutes. A backlog of 77 PRs is about 40 clusters. A nightly run of 2 or 3 new PRs is one or two clusters.
