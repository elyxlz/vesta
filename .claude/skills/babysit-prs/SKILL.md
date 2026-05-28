---
name: babysit-prs
description: >
  Use when the user asks to babysit PRs, fix CI, make all PRs green, unblock open
  PRs, resolve merge conflicts on PRs, or run "babysit-prs". Walks every open PR
  with failing checks or merge conflicts, diagnoses the issue, pushes a fix to
  the PR's branch, and leaves a comment on the PR describing what was changed
  and why. Aggressive: will modify code, tests, lockfiles, configs as needed to
  make checks pass and resolve conflicts, subject to the hard rules below.
  Multiple red/conflicting PRs are processed in parallel via worktree-isolated
  subagents.
---

# Babysit PRs

Make every open PR mergeable: green CI and no merge conflicts. One pass: discover, fix, push, comment, report.

## Workflow

1. **Discover broken PRs.**
   ```
   gh pr list --state open --limit 100 \
     --json number,title,headRefName,isDraft,author,labels,statusCheckRollup,mergeable
   ```
   A PR is **in scope** if it's open, not draft, and *either*:
   - **Red CI:** at least one entry in `statusCheckRollup` has `conclusion` in `FAILURE | TIMED_OUT | CANCELLED | ACTION_REQUIRED | STALE`, or a `StatusContext` with `state` in `FAILURE | ERROR`, OR
   - **Merge conflict:** `mergeable == "CONFLICTING"` (sometimes paired with `mergeStateStatus == "DIRTY"`).

   `mergeable == "UNKNOWN"` means GitHub hasn't computed it yet — re-fetch with `gh pr view <N> --json mergeable,mergeStateStatus` after a few seconds, or fall back to a local `git merge-tree --write-tree origin/<base> pr/<N>` and grep for `^<<<<<<<` to determine truth. Don't treat UNKNOWN as a conflict on its own.

   PRs with only `PENDING` checks and no conflict are *not* in scope, just wait. PRs that are entirely green AND mergeable are not in scope.

   **Skip** if any of:
   - `isDraft: true`
   - labels include `wip`, `blocked`, `do-not-merge`, or `needs-design`
   - PR is from a fork (you can't push to fork branches without extra setup): surface in the report instead
   - PR's last commit is by you (`vesta-upstream` / agent) and the same failure (or same conflict set) already shows your "babysit-prs" comment with that commit SHA: you already tried, don't loop

2. **Fan out per PR.** For each in-scope PR, dispatch a subagent with `Agent({ subagent_type: "general-purpose", isolation: "worktree", ... })` so each PR is fixed in its own checkout. Run them in parallel by sending all `Agent` calls in one message. Each subagent's prompt must include:
   - PR number, title, head branch, base branch
   - Why it's in scope: failing checks (names + run IDs) and/or `mergeable: CONFLICTING`
   - Verbatim copy of the "Per-PR loop" section below
   - The "Hard rules" section below

3. **Final report.** After all subagents return, summarize:
   - PRs now green and mergeable ✅
   - PRs that pushed a fix but CI is still running ⏳
   - PRs still red or still conflicting after retries: list them with the diagnosis the subagent landed on, so the user can decide what to do
   - PRs skipped: list with reason (draft, fork, label, already-tried)

## Per-PR loop (what the subagent does)

The subagent has its own worktree. Inside it:

1. **Check out the PR's branch:**
   ```
   gh pr checkout <N>
   ```

2. **Resolve merge conflicts (if any).** If the PR is in scope because `mergeable: CONFLICTING`, or you can see conflicts after `git fetch origin <base> && git merge --no-commit --no-ff origin/<base>`:
   - Merge the base branch into the PR branch (do *not* rebase — rebase requires `--force` push, which is forbidden):
     ```
     git fetch origin <base>
     git merge origin/<base>
     ```
   - Resolve each conflicted file by hand. The PR's intent should usually win for files the PR is touching; for files the PR didn't touch but base did, take base. When unsure which side is right, read both sides' commit messages (`git log --oneline HEAD..origin/<base> -- <file>` and `git log --oneline origin/<base>..HEAD -- <file>`) and reconcile semantically — don't just pick one side blindly.
   - For lockfiles (`Cargo.lock`, `package-lock.json`, `uv.lock`): regenerate from scratch instead of hand-merging — `cargo build`, `npm install`, `uv lock`. Commit the regenerated lockfile.
   - Run the PR's relevant test suite locally after the merge to confirm nothing semantic broke (e.g., a renamed function on master that the PR still calls).
   - Commit the merge with the default merge message (don't amend, don't squash).
   - If conflicts are deep enough that resolution requires design decisions you don't have context for (e.g., the PR and master both rewrote the same module differently), stop and post the diagnosis comment. Do not guess.

3. **Pull failure logs.** Skip if the only issue was a merge conflict and CI was green. Otherwise, for each failing check:
   ```
   gh pr checks <N>                                    # list checks + run IDs
   gh run view <run-id> --log-failed                   # log lines for the failed step
   ```
   Read enough log to identify the root cause. If the failure is in a step you don't recognize (custom action, deploy job), `gh run view <run-id>` for the full log.

4. **Reproduce locally when possible.** Tests, lint, typecheck, build all run locally: run the same command the CI step ran (look at the step's `name` and the workflow file under `.github/workflows/`). For `cargo test -p vestad`, `uv run pytest`, `npm -w @vesta/web run check`, etc., run them and confirm you see the same failure.

5. **Diagnose.** Write down the root cause in one sentence before changing anything. If it's "the test asserts X but the code does Y", decide which side is wrong: see "Code vs test" under Hard rules.

6. **Fix.** Edit the minimum set of files. Re-run the failing check locally; only proceed when it passes locally.

7. **Commit.** One commit per CI fix, message format:
   ```
   fix(ci): <one-line summary>

   <2-3 lines on what failed and why this fixes it>
   ```
   The merge commit from step 2 (if any) is separate and stays as-is.

8. **Push.** `git push` to the PR's branch. Never `--force`. This pushes both the merge commit (if any) and the fix commit.

9. **Wait for CI to re-run.** Don't report green from your local run: let GitHub run it. Poll:
   ```
   gh pr checks <N> --watch
   ```
   or sleep + poll in a loop with a 5-minute cap per check. Also re-check `gh pr view <N> --json mergeable` to confirm the conflict is gone (`MERGEABLE`) before declaring success.

10. **Outcome:**
    - **All checks green AND `mergeable == "MERGEABLE"`:** post the success comment (template below) and stop.
    - **Different failure than before:** the fix exposed a new problem. Loop back to step 3 (max 3 attempts total per PR).
    - **Same failure persists, or the merge re-conflicts because base moved again:** post the diagnosis comment (template below) explaining what you tried. Stop, do not retry.

## Comment templates

**Success:**
````
🤖 babysit-prs

Was failing on:
- `<check-name>` / `merge conflict in <file>`: <one-line cause>
- `<check-name>` / `merge conflict in <file>`: <one-line cause>

Pushed [`<short-sha>`](<commit-url>):
- `<file>:<line>`: <what changed and why>
- `<file>:<line>`: <what changed and why>

CI is now green and the branch is mergeable ✅
````

**Diagnosis (still red or still conflicting after retries):**
````
🤖 babysit-prs

Still red / conflicting after <N> attempts. Root cause as best I can tell:

<2-4 sentences on the underlying issue — distinguish CI failure vs. unresolvable merge conflict>

Tried:
- <one-line attempt 1>: <why it didn't work>
- <one-line attempt 2>: <why it didn't work>

Leaving for human review: the fix likely needs <design decision / context I don't have>.
````

Post comments with `gh pr comment <N> --body-file <tmpfile>`: heredocs in shell pipelines mangle backticks.

## Hard rules

The skill is aggressive about *fixing*, not about *bypassing*. These rules hold even when bypassing would make CI green faster:

- **Never weaken or skip a test** to suppress a failure unless the test itself is provably wrong (typo in assertion, race that the test owner already documented as flaky in `CLAUDE.md` / commit message). The default assumption when a test fails is that the *code* is wrong. Fix the code.
- **Never `--no-verify`, `--no-gpg-sign`, or any other hook bypass.** If a pre-commit hook fails, fix the underlying issue.
- **Never `--force` push.** Resolve conflicts by merging base *into* the PR branch, never by rebasing the PR branch onto base. If a rebase is genuinely needed (e.g., the PR's history is broken), surface it to the user.
- **Never resolve a conflict by deleting one side blindly.** Read both sides' history. If you can't reconcile them in under ~10 minutes, post the diagnosis comment instead of guessing.
- **Never modify `.github/workflows/`** to delete or skip a check. Workflow edits are allowed only when the failure is *in the workflow itself* (e.g. a syntax error you introduced earlier in this run).
- **Never amend commits on the PR branch.** Always add a new commit. The user can squash at merge time.
- **Never close, merge, approve, re-request review, or change labels** on the PR. The skill only pushes fixes and posts one comment per attempt.
- **Never touch unrelated PRs** (only the one your subagent was dispatched for).
- **Never delete a test, snapshot, or fixture** to make red go green. Update them only if the underlying behavior change is intentional and already merged on the PR's main commits.
- **Don't retry beyond 3 attempts per PR.** A skill that loops on the same failure burns CI minutes and produces noisy comment threads. Stop and surface.
- **Don't proceed if `gh auth status` is unauthenticated.** Stop the whole skill and tell the user to log in.

### Code vs test

When a test fails, decide which side to change:

- **Fix the code** when: the test asserts a documented behavior, an API contract, an invariant in CLAUDE.md, or matches the PR's stated goal. Default here.
- **Fix the test** when: the PR explicitly intends to change the behavior the test pins, the test was added in the same PR and the assertion is fragile (timestamps, ordering, exact strings), or the test owner left a "TODO: fix flake" comment. State this reasoning in the commit message.

If you can't decide in under 5 minutes of looking, stop and post the diagnosis comment. Don't guess.

## Discovery details

### Mergeable field

| Value | Meaning | Action |
| --- | --- | --- |
| `MERGEABLE` | No conflicts | Skip (for the merge-conflict criterion) |
| `CONFLICTING` | Has conflicts | **In scope** |
| `UNKNOWN` | GitHub hasn't computed yet | Re-fetch via `gh pr view <N> --json mergeable` after a few seconds. If still UNKNOWN, run `git fetch origin <base> && git merge-tree --write-tree origin/<base> pr/<N>` locally and grep for `^<<<<<<<` to determine truth. Don't assume CONFLICTING. |

### Status check rollup

`statusCheckRollup` shape from `gh pr list --json statusCheckRollup`:

```json
[
  {"__typename":"CheckRun","name":"test-linux","conclusion":"FAILURE","detailsUrl":"..."},
  {"__typename":"StatusContext","context":"netlify","state":"SUCCESS"}
]
```

Both `CheckRun` (Actions) and `StatusContext` (legacy statuses, e.g. Netlify, Codecov) count. Map their states uniformly:

| Source | Field | Failing values |
| --- | --- | --- |
| `CheckRun` | `conclusion` | `FAILURE`, `TIMED_OUT`, `CANCELLED`, `ACTION_REQUIRED`, `STALE` |
| `StatusContext` | `state` | `FAILURE`, `ERROR` |

`null` / missing conclusion = still running, not a failure.

## Don'ts

- Don't run on PRs to repos you weren't invoked from: restrict to the current repo (`gh pr list` defaults to it; don't pass `--repo` overrides).
- Don't post a comment on a PR you didn't change. Silent skips don't need announcements.
- Don't post multiple comments per push: one comment per attempt, batched with all the changes from that attempt.
- Don't run this skill against `master`/`main`: only against PR branches.
- Don't delegate to `/ultrareview` or other interactive commands. Babysit-prs is autonomous; it produces actions, not review.
