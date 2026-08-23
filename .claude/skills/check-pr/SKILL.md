---
name: check-pr
description: >
  Use when the user asks to check a PR, review a PR, sanity-check a pull request,
  ask whether a PR is correct or ready, or run "check-pr <number>". Also runs
  automatically on newly opened PRs. Use it whenever the question is whether a
  change is noise, is bugged, or is worth merging. Read only: it never pushes,
  merges, or closes, so reach for polish-pr instead when the PR needs changing.
---

# Check a PR

Answer one question for a maintainer who has not opened the diff: **is this pull request noise, is it bugged, or is it worth merging?** Everything in the comment exists to support that answer and nothing else.

The stance is adversarial. The burden is on the pull request, not on you: assume the description is optimistic and that the author stopped looking once it passed. Your value is the objection nobody else raised, and a change nobody argued against is a change nobody checked.

Read only. Never push a commit, never merge, never close, never edit the PR. Changing the PR is `polish-pr`'s job, and it runs only when a human asks for it.

## The three answers

**NOISE.** The change should not be carried at all, whatever its code quality. It solves a problem nobody has, fixes a symptom whose cause is elsewhere, churns code for taste, rebuilds something the repo already has, adds a knob nobody asked for, or was already fixed on master (name the commit that did it). Say which of those it is. This is the answer maintainers most often have to reach on their own, so reach it for them when it is true, and do not soften it because the code is tidy.

**BUGGED.** The change is worth having but is wrong as written: it does not do what it claims, breaks something else, or misses a case it must handle. Name the case.

**MERGE.** You attacked it and it held. Say so plainly. A verdict that never says MERGE is worth as little as one that always does.

## Ground truth

When the PR belongs to the repo this tree tracks, the dispatcher launches you in a fresh worktree reset to `origin/master`, fetched at launch, so a plain file read is today's code. Confirm the guarantee rather than assuming it: `git fetch -q origin master; git rev-parse HEAD origin/master` must print the same sha twice. When it does not (a fallback launch in an undispatched or stale tree), no working-tree read is citable: read current code with `git show origin/master:<path>` and search it with `git grep <pattern> origin/master -- <paths>` instead. A stale tree resolves plain reads to history, and a verdict built on deleted code files a false regression against the exact PR that removed it.

The PR's own version is never on disk either way: read its diff with `gh pr diff`, resolve `head=$(gh pr view <n> --json headRefOid -q .headRefOid)`, and run tests in a worktree of it (`git fetch origin "pull/<n>/head" && git worktree add <dir> "$head"`), never in the tree you woke up in. When the PR belongs to a different repo than this tree (`git remote get-url origin` disagrees), nothing local is ground truth: read base and head through `gh` alone.

Cite the ref you read in every finding (`master@<short-sha>` or `head@<short-sha>`), and link cited lines with the full sha in the URL, so the citation reproduces and a stale read is visible on its face. Subagents inherit all of this: it rides along in every delegation prompt.

## The pipeline

Run the review as this sequence. Steps 1 to 3 are cheap gates and context; step 5 is the fan-out; steps 6 to 8 turn findings into the one comment. Make a todo list from these steps first.

**1. Eligibility (one Haiku agent).** Check whether the PR (a) is closed, (b) is a draft, (c) does not need review (an automated PR, or trivial and obviously fine), or (d) already carries your review. On the automatic new-PR run, any of those ends the review. On an explicit `@vestabot` mention, (a) and (b) still end it, but (c) and (d) do not: a maintainer asked, so re-check, reviewing what changed since your last comment rather than repeating it.

**2. Repo rules (one Haiku agent).** Collect the paths (not contents) of the governing files: the root `CLAUDE.md`, any `CLAUDE.md` in directories the PR touches, and any repo skill covering the touched area. These bind step 5's compliance lens.

**3. Summary (one Haiku agent).** Have it read the PR and return what the change claims to do, the linked issues, and the version footer if present (`Submitted by **<name>** on vesta vX.Y.Z`, appended by `upstream` to every agent PR).

**4. Confirm ground truth** as the section above defines: verify the tree is at fetched `origin/master` (or fall back to `git show` reads), and resolve `$head`. Every agent below receives the tree's status, `$head`, and the ground-truth rules in its prompt.

**5. Parallel reviewers (Sonnet agents, launched together).** Each returns a list of issues, and for each issue the reason it was flagged and the ref-pinned evidence:

- **Compliance.** Audit the diff against the step 2 files. CLAUDE.md is guidance for writing code, so not every instruction applies in review; flag only what the file actually calls out. Include this repo's standing bans CI does not always catch: inline lint escapes, comment blocks over 8 lines, banned Python accessors (`.get()`/`getattr`/`hasattr`), `.unwrap()` on fallible Rust paths, `any` in TypeScript, and under `agent/` prose that narrates a previous design (apply the `vesta-prompt-guide` encounter test first: prose describing a before and after the agent can still encounter on disk stays; only changelog narration with nothing on disk to act on is the violation).
- **Bug scan.** Read the file changes and hunt real bugs in them, pressing hardest where the code looks finished and the tests are green. The known misses, each of which has bitten a merged PR: a shared flag flipped for one reader (enumerate every reader); happy path only; tests that encode the author's assumptions (exercise the paths the *other* users of a shared mechanism take); right idea, wrong execution (name case X; that is BUGGED, not MERGE); a probe whose setup dies before the branch it claims to pin; real people in fixtures. Trace the failure to its cause and check the change addresses that rather than the visible symptom, name a simpler change when one exists, and cover the failure, empty, and concurrent paths, not only the happy one.
- **History.** Establish how far the PR's world is from today's. Do not trust the git base: agent PRs are written on a box's stock snapshot and pushed as a fresh branch, so the merge-base reads current while the code the author saw may be releases old. Resolve the written-on version from the step 3 footer to its `vX.Y.Z` tag; only with no footer fall back to `git merge-base "$master" "$head"`. Walk `git log --oneline <tag-or-base>..$master -- <paths>` plus a pickaxe (`git log -S`) on the load-bearing symbol, read the PRs those commits came from, read git blame for the touched lines, then open today's code path and answer one of: `still broken` (the line that proves it), `already fixed by <commit/PR>` (the line that fixed it), or `partially fixed` (what remains).
- **Prior review.** Read previous PRs that touched these files and the comments on them; a concern raised there may apply verbatim here. When another open PR touches the same function, read that diff too and say whether they compose, conflict, or need a merge order.
- **Comment compliance.** Read the code comments in the modified files and check the diff honors what they constrain: an invariant stated above a function the diff breaks is a finding.
- **Runtime seat** (only when the diff touches `agent/`). Vesta consumes these files at runtime, sometimes on a weaker model. An error message that names its own override is a bypass instruction. Run every command the prose tells the agent to run against the box's real layout. Sweep the whole touched file for contradictions, not just the hunks. A changed record, file, or wire shape must find every reader in every language, tests and scripts included. Say what the change costs a weak model. And one agent's incident is not fleet doctrine: before a workaround ships fleet-wide, check whether master already fixed the cause, whether a stock mechanism already owns the job, and whether the guidance builds a second homemade layer beside the stock one; entrenching a redundant layer is NOISE even when every sentence is true.

**6. Score every issue (one Haiku agent per issue, in parallel).** Each agent gets the PR, the issue, and the step 2 file list, double checks the issue, and returns a confidence score. For issues flagged from a CLAUDE.md, it verifies the file actually calls that out. Give each agent this rubric verbatim:

- 0: Not confident at all. This is a false positive that doesn't stand up to light scrutiny.
- 25: Somewhat confident. This might be a real issue, but may also be a false positive. The agent wasn't able to verify that it's a real issue. If the issue is stylistic, it is one that was not explicitly called out in the relevant CLAUDE.md.
- 50: Moderately confident. The agent was able to verify this is a real issue, but it might be a nitpick or not happen very often in practice. Relative to the rest of the PR, it's not very important.
- 75: Highly confident. The agent double checked the issue, and verified that it is very likely a real issue that will be hit in practice. The existing approach in the PR is insufficient. The issue is very important and will directly impact the code's functionality, or it is directly mentioned in the relevant CLAUDE.md.
- 100: Absolutely certain. The agent double checked the issue, and confirmed that it is definitely a real issue, that will happen frequently in practice. The evidence directly confirms this.

Drop every issue scoring under 80. False positives to score down: something that looks like a bug but is not, pedantic nitpicks a senior engineer would not raise, anything a linter or typechecker catches (CI runs those; do not run build or typecheck yourself), general code-quality wishes not required by the repo rules, issues explicitly silenced in code, and intentional behavior changes that are the point of the PR. One vesta override on the official taxonomy: "pre-existing" alone does not score an issue down. Nothing is pre-existing or out of scope until the scorer has shown the PR's own changed surface cannot reach it: its diff, its documented flow, and the callers of the functions it touches. A defect whose mechanism predates the PR is still this PR's defect when the change's own flow triggers it.

**7. Settle what survives.** For a surviving finding that a command can settle, run it in the head worktree and capture the line that matters. Trust a test only once you have seen it fail: revert the fix in the worktree, or flip the constant it pins, and confirm the right test goes red. When a pass could depend on timing, ordering, or filename sorting, run it twenty times before crediting it. Re-run the step 1 eligibility check so a PR that merged or closed mid-review gets no comment.

**8. Comment**, in the reporting form below.

Also confirm before writing the verdict, whoever's lens it fell through:

- **It fixes the issue it claims to.** Read the closing-keyword issue itself, not the PR's description of it. Distinguish fixing it, fixing part of it, fixing something adjacent, and not addressing it at all.
- **The stated goal is reached end to end.** Run the documented or changed sequence to the state a user actually ends in. Each command being individually valid is not the goal reached.
- **Shipped migrations are append-only.** A diff editing a released file under `agent/core/migrations/` reaches nobody; the fix is a new migration file. Walk any migration prompt as a literal-minded executor: every step checks before acting and is safe half-done twice.
- **It is mergeable.** CI green, no conflicts, not draft, scoped to one concern.

**Map findings to the verdict mechanically.** The verdict is a function of the surviving findings, not a closing impression. Any Blocking finding makes it `BUGGED`, or `NOISE` when the change should not be carried at all (including `already fixed by <commit>` from the history lens). A bypassable safety or auth control, lost or corrupted data, or a flow that does not reach its own stated goal is always Blocking, however narrow the window. No Blocking finding, a real problem solved, and the pipeline completed makes it `MERGE`. When two reviews of one PR disagree, the reachable Blocking finding outranks the review that only confirmed the parts are valid: re-derive from the code, never average the verdicts.

## Reporting

You get one run, and it ends when you stop. Post the comment before you finish, even with things unresolved: you cannot wait for CI or come back later. Anything still pending goes on the CI line, naming what to watch, and the verdict still answers what you can see now.

Post one comment, in the labelled form below. No opening line, no lead-in, no scene setting: the first characters of the comment are the first label. A reader should be able to find any one thing without reading the rest. Keep it brief, no emojis, and link every cited file and line with the full sha in the URL (`https://github.com/<org>/<repo>/blob/<full-sha>/<path>#L10-L14`), never a branch name.

Write every label every time, in this order. When a label has nothing under it, write `none` rather than dropping it, so a missing section never has to be interpreted.

**Fixes:** the linked issue and whether this actually closes it: fully, partly (say which part is left), something adjacent (say what), or nothing. With no issue linked, write `nothing linked` and one clause naming the problem it solves.

**Blocking:** findings that should stop the merge. Two lines each, no more:

- line one: `` `file:line` ``, what the code does, and what goes wrong because of it
- line two, indented and starting `Proof:`, the thing that settles it

**Non-blocking:** everything else worth saying, same two lines. Do not argue for them; a maintainer decides. When a CI check is red, one line here names which kind, so the maintainer knows the move: a real failure the diff caused, a fixable nit one commit from green, a flake unrelated to the change (often red on `master` too), or a platform outage. Read the failing job's log tail before classifying: a job that dies before checkout ("Failed to resolve action download info", "Service Unavailable") is GitHub, not the PR, and a rerun is the whole fix.

**Verdict:** `NOISE`, `BUGGED`, or `MERGE`, then a dash and the one thing that decided it. Judge the diff and nothing else: a red check is on the PR page already, and a sound change with a formatting failure is still `MERGE`.

### Proof

A finding a maintainer has to re-derive costs more than it saves. Every finding carries the one thing that lets them start from your work instead of from scratch, in a single line:

- **the command and what it printed**, trimmed to the line that matters: `` uv run pytest -k send_fails → 1 failed, AssertionError: notification file missing ``
- **the input or state that triggers it**, concretely: `` card "4111 1111 1111 1111" → returns [], the space-separated form never matches ``
- **the two places that contradict each other**, when it is a mismatch rather than a crash: `` writes `success:false` at `messaging.go:88`, read as exit 0 at `cli.go:149` ``

Never write proof that cannot be checked: `verified locally`, `I audited this`, `tests pass`, `looks correct`. Those are claims about you, and a reader can do nothing with them. If you could not settle a finding, say `Proof: none, read only` and let its weight fall accordingly.

Findings state what breaks, not what you did. Never narrate the review, never list what you checked that turned out fine, never restate the PR description. **150 words is the ceiling for everything above the rule.** Past that you are explaining rather than reporting.

<example>
**Fixes:** #412 fully.

**Blocking**
- `core/loops.py:88` deletes the notification file before the send is confirmed, so a failed send loses the message with nothing to retry from.
  Proof: point it at a closed socket, `uv run pytest -k send_fails` → 1 failed, notification file already unlinked.

**Non-blocking**
- `core/loops.py:120` catches bare `Exception` around the whole batch, so one bad notification drops the rest of it.
  Proof: none, read only.

**Verdict:** BUGGED, the delete ordering loses messages on send failure, two-line fix.
</example>

<example>
**Fixes:** nothing linked, tightens the reauth path on the sync socket.

**Blocking**
- `AuthProvider/index.tsx:60` awaits an untimed fetch during boot, so an unreachable gateway hangs the splash until the OS gives up instead of falling through to the disconnected overlay.
  Proof: gateway down, splash held 127s before `App.tsx:29` rendered; no upper bound on that path.

**Non-blocking:** none.

**Verdict:** BUGGED, boot blocks on a network call that has no timeout.
</example>

Judge the change on its merits even when you wrote the code yourself, and say `NOISE` or `BUGGED` when you believe it, including when the person who asked clearly wants it in. A verdict that always says MERGE is worth less than no verdict.

When the PR would benefit from the simplify and tidy pass that `polish-pr` does, say so in one line and name the skill, so a maintainer can ask for it. Do not run it yourself: it pushes commits, and that is the maintainer's call.

End the comment with this exact line, alone on the last line, after everything else including the verdict and the footer:

```
<!-- vestabot:reply -->
```

It renders as nothing, and it is what stops the loop treating your own comment as a fresh request. The footer below names the trigger, and you post under an account that also belongs to a human, so without that line your comment wakes you again on the next poll.

Nobody asked for this check, so close with one line under a `---` rule saying how to ask for the next thing. One line, not a paragraph:

```
---
Maintainers: mention `@vestabot` to re-check, run `polish-pr`, or fix red CI.
```
