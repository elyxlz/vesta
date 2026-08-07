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

**NOISE.** The change should not be carried at all, whatever its code quality. It solves a problem nobody has, fixes a symptom whose cause is elsewhere, churns code for taste, rebuilds something the repo already has, or adds a knob nobody asked for. Say which of those it is. This is the answer maintainers most often have to reach on their own, so reach it for them when it is true, and do not soften it because the code is tidy.

**BUGGED.** The change is worth having but is wrong as written: it does not do what it claims, breaks something else, or misses a case it must handle. Name the case.

**MERGE.** You attacked it and it held. Say so plainly. A verdict that never says MERGE is worth as little as one that always does.

## Critique the solution, not only the code

Read the diff closely, then judge the thinking behind it:

- **Is it the right fix?** Trace the failure to its cause and check the change addresses that rather than the symptom that happened to be visible. A guard at the call site, when the bug is in the callee, is a patch over a symptom.
- **Is it the smallest fix?** Name a simpler change when one exists. Abstractions for a single caller, options nobody asked for, and defensive branches for impossible states all belong in the review.
- **What did the author not consider?** Concurrency, partial failure, restart, empty and enormous inputs, the second caller, the fleet already running the old shape.
- **What does it cost?** New coupling, a widened interface, a dependency, or state somebody has to migrate later.

## Attack it before accepting it

Try to break the change rather than reading it for plausibility. Find the input, state, or ordering where it misbehaves, and look hardest where there are no tests: a suite tells you what the author thought of, not what is true.

Trust a test only once you have seen it fail. Revert the fix in your local copy, or flip the constant it pins, and confirm the right test goes red; a suite that stays green either way pins nothing. And when a pass could depend on timing, ordering, or filename sorting, run the test twenty times before crediting it: one pass proves it can pass, not that it passes.

Never speculate about code you have not opened. Read the code paths the diff touches before saying anything about them, and where running something settles a question, run it. The `check.sh` subcommands in `CLAUDE.md` are the ones CI uses.

Find everything first, then filter once. While reading, collect every concern at any severity rather than deciding as you go whether one is worth mentioning: judging severity while looking suppresses real findings. Then make one pass over the list and drop only what you could not substantiate, keeping anything real however small. Filter on "is this true", never on "is this important enough".

Say so plainly when the change is simply good. A review that manufactures objections to look thorough is worth as little as one that rubber-stamps.

Work through the diff yourself. Delegate to a subagent only when the diff is genuinely too large to hold in one reading, and then split it by area so each subagent owns a different part rather than re-reviewing the same code. One is usually enough. Do not spawn a subagent to double-check a finding you already have.

## The junior-code lens

Press hardest when the code looks finished and the tests are green: that is exactly where a junior author stopped. The symptom-versus-cause check above is the first pass; these are the misses it does not catch on its own, and each one has bitten a merged PR:

- **A shared flag flipped for one reader.** The change sets a field, flag, or column that several behaviors read, and only the reader the author cared about was checked. Enumerate every reader and say what the change does to each; the break hides in the one they forgot.
- **Happy path only.** No guard for contradictory, empty, or impossible input. The branch that "can't happen" is silently wrong the first time it does.
- **The tests encode the author's assumptions.** Green proves their mental model, not the truth. Find the case the tests skip; when the PR touches a shared mechanism, exercise the paths its *other* users take, not the one the author wrote a test for. The bug the author would have tested for is not the one still in the diff.
- **Right idea, wrong execution.** The direction is correct and the fix is worth having, and it still double-books, drops, or duplicates in case X. Name X. That is `BUGGED`, not `MERGE`: a needed fix carried in wrong is still carried in wrong.
- **Stale base.** A PR correct when it was written can be wrong against today's `master`. Read the current code paths, including whatever merged *after* it was opened, since a later change may have repurposed a field it relies on. When another open PR touches the same function, read that diff too and say whether they compose, conflict, or need a merge order.
- **The probe never reaches the branch.** A test can pass while its setup dies earlier: a "corrupt record" written as `"1234 "` splits back to a valid one, so the tolerance branch it claims to pin never runs. Check what the setup actually produces before crediting the assertion.
- **Real people in fixtures.** Test data copied from a live incident carries real names, addresses, and employers into the repo forever. Flag it: fictional equivalents exercise the same code.

## The runtime seat

Most changes under `agent/` are consumed by Vesta at runtime, mid-conversation, sometimes on a weaker model than the one reviewing them. Judge them from that seat, not only as code:

- **An error message that names its own override is a bypass instruction.** A refusal ending "unset X to allow it" or "pass --force" will be followed by exactly the model the guard exists to stop. The right refusal states what happened and the next step that stays inside the rules, usually: tell the user.
- **Run every command the prose tells the agent to run**, against the box's real layout: the binary must be in the image, the path, table, git ref, and field must exist, and the output must mean what the doc says. A CLI the image does not ship, a ref that does not exist, and a snippet that crashes on default config have all passed review as prose. `Proof:` is the command run against a fabricated home.
- **Sweep for contradictions.** Read the whole file the diff touches, not the hunks: a new paragraph that disagrees with a standing one gives the agent opposing instructions, and the weaker the model the more that costs. Two open PRs solving the same problem are the same hazard; say which one is law and what survives from the other.
- **A changed format must find every reader.** When the diff changes a record, file, or wire shape, enumerate every consumer in every language, including tests, watchdogs, and shell scripts. The recurring defect is a reader still parsing the old shape; five hid in one PR this way.
- **Say what the change costs a weak model.** Fewer decision points, refusals that state the next step, and rules an agent predicts without reading code are net gains worth extra implementation work; a subtler or wordier runtime surface is a loss even when the code got better. Name which the PR is.
- **One agent's incident is not fleet doctrine.** Agent-authored PRs generalize from a single box's bad day, against the released code, with the circumstances mostly unrecoverable from the PR. Before prose or a workaround ships fleet-wide, ask three things: is the underlying cause already fixed on master, does a stock mechanism already own the job (a watchdog, a preflight, a contract test), and does the guidance teach agents to build a second homemade layer beside the stock one? Guidance that entrenches a redundant layer is `NOISE` even when every sentence in it is verifiably true; the fix for a box where the stock mechanism failed is diagnosing that box.

## Was it already fixed?

Establish how far the PR's world is from today's before trusting anything the diff assumes. Do not trust the git base for this: most PRs here are written by agents on their own boxes against the stock snapshot of the version they run, and `upstream-pr` pushes that work as a branch cut fresh from master, so the merge-base reads current while the code the author actually saw may be many releases old. The version the PR was written on is in the body: `upstream-pr` appends `Submitted by **<name>** on vesta vX.Y.Z` to every agent PR. Read that version and resolve it to the `vX.Y.Z` release tag; only when the body carries no version footer (a human branch, cut from the master it was written against) fall back to `git merge-base origin/master <head>`. Either way, compare against the version on `origin/master` (`git show origin/master:agent/core/pyproject.toml`). A gap of releases means everything the diff touches must be re-read in today's code, and it means the problem itself may already be gone.

When the written-on point is behind master, fan out one subagent dedicated to that single question, in parallel with your own read of the diff. Give it the problem the PR claims to solve and the files it touches, and have it walk `git log --oneline <tag-or-base>..origin/master -- <paths>` plus a pickaxe (`git log -S`) on the load-bearing symbol, read the PRs those commits came from, then open today's code path and say whether the defect still exists. It returns a report, not an opinion about the diff: the written-on version and how it was determined (body footer or merge-base), master sha and version, the commits since that touch the same ground, and one of `still broken` (with the line that proves it), `already fixed by <commit/PR>` (with the line that fixed it), or `partially fixed` (what remains). This is the one delegation that always pays for itself: it needs no context from your read, so it costs you nothing to launch first, and it settles a question you would otherwise answer late or not at all.

Fold the report into the comment, not alongside it: a PR whose problem master already fixed is `NOISE` (superseded; name the commit that did it) whatever its code quality, `partially fixed` reframes what the PR still buys, and `still broken` is what lets the verdict stand on today's code rather than the base's.

## Make the verdict reproducible

Two runs of this skill on the same PR should reach the same verdict. They diverge when they trace different things, scope a finding differently, or map findings to a verdict by feel. Close those three gaps every time.

**Cover the same ground.** Before writing a verdict you must have traced each of these and know its result, whether or not it becomes a finding:
- the PR's stated goal, end to end: run the documented or changed sequence to the state a user actually ends in, and confirm that state is the claimed one. Each command being individually valid is not the goal reached; "the flags are accepted" is not "read-only is in force".
- every reader of anything the diff changes (a record, flag, format, column, wire field), in every language, tests and scripts included.
- the failure, empty, and concurrent path of the main change, not only its happy path.
- each closing-keyword issue, read from the issue itself, actually closed.

A `MERGE` names the ground it attacked and held ("attacked on completeness, the filter edges, and the failure path"); an unstated attack surface is an unfinished review, not a clean one.

**Scope by reachability, not by feel.** Nothing is "pre-existing" or "out of scope" until you have shown the PR's own changed surface cannot reach it: its diff, its documented flow, and the callers of the functions it touches. A defect whose mechanism predates the PR is still this PR's defect when the change's own flow triggers it. "That is the crash path, not this PR" is the exact miss that ships: test reachability before you file it away.

**Map findings to the verdict mechanically.** The verdict is a function of the findings, not a closing impression. Any Blocking finding makes it `BUGGED`, or `NOISE` when the change should not be carried at all. A bypassable safety or auth control, lost or corrupted data, or a flow that does not reach its own stated goal is always Blocking, however narrow the window. No Blocking finding, a real problem solved, and the coverage floor met makes it `MERGE`. When two reviews of one PR disagree, the reachable Blocking finding outranks the review that only confirmed the parts are valid: re-derive from the code, never average the verdicts.

## Also confirm

**It fixes the issue it claims to.** Find the issue from a closing keyword in the PR body (`fixes #N`, `closes #N`, `resolves #N`) and read the issue itself, not the PR's description of it. Distinguish fixing it from fixing part of it, fixing something adjacent, and not addressing it at all. With no issue linked, say what problem the PR appears to solve and whether it is worth carrying.

**It is right for this repository.** Judge against this repo's rules rather than generic taste. `CLAUDE.md` governs architecture principles, code conventions, and the PR rules; the language section for whatever it touches applies; a skill covering that area applies too. Watch for the repo-wide bans CI does not always catch on a PR: inline lint escapes, comment blocks over 8 lines, banned Python accessors (`.get()`/`getattr`/`hasattr`), `.unwrap()` on fallible Rust paths, `any` in TypeScript, and under `agent/` a docstring or comment that narrates a previous design or restates the PR's rationale (the agent reads it cold, so it must state the current mechanism only). Apply the `vesta-prompt-guide` encounter test before flagging this, so the call is deterministic rather than a matter of taste: prose describing a before and after the agent can still **encounter** on disk (a stale record a migration converges, a legacy shape a reader must tolerate, the source state a `LEGACY(...)` block exists for) is correct and stays; only changelog narration with nothing on disk to act on (what this replaces, what it used to do, how many files it folds) is the violation. This keeps migration and convergence prose, which describes a before and after by necessity, from being flagged as a false positive.

**Shipped migrations are append-only.** A diff that edits a file under `agent/core/migrations/` already in a release reaches nobody who ran it; the fix is a new migration file. Walk any migration prompt as a literal-minded executor: every step checks before acting, is safe half-done twice, and the mark-applied step is gated on nothing remaining.

**It is mergeable.** CI green, no conflicts, not draft, scoped to one concern.

## Reporting

You get one run, and it ends when you stop. Post the comment before you finish, even with things unresolved: you cannot wait for CI or come back later. Anything still pending goes on the CI line, naming what to watch, and the verdict still answers what you can see now.


Post one comment, in the labelled form below. No opening line, no lead-in, no scene setting: the first characters of the comment are the first label. A reader should be able to find any one thing without reading the rest.

Write every label every time, in this order. When a label has nothing under it, write `none` rather than dropping it, so a missing section never has to be interpreted.

**Fixes:** the linked issue and whether this actually closes it: fully, partly (say which part is left), something adjacent (say what), or nothing. With no issue linked, write `nothing linked` and one clause naming the problem it solves.

**Blocking:** findings that should stop the merge. Two lines each, no more:

- line one: `` `file:line` ``, what the code does, and what goes wrong because of it
- line two, indented and starting `Proof:`, the thing that settles it

**Non-blocking:** everything else worth saying, same two lines. Do not argue for them; a maintainer decides.

**Verdict:** `NOISE`, `BUGGED`, or `MERGE`, then a dash and the one thing that decided it. Judge the diff and nothing else. CI is not your business: a red check is on the PR page already, it says nothing about whether the change is right, and a sound change with a formatting failure is still `MERGE`. When a check is red, still name which kind in one line under **Non-blocking**, so the maintainer knows the move: a real failure the diff caused, a fixable nit one commit from green (a comment over the cap, a banned accessor, a format miss), a flake unrelated to the change (often red on `master` too, green on a re-run), or a platform outage. Read the failing job's log tail before classifying: a job that dies before checkout ("Failed to resolve action download info", "Service Unavailable") is GitHub, not the PR, and a rerun is the whole fix.

## Proof

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
