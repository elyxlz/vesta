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

Never speculate about code you have not opened. Read the code paths the diff touches before saying anything about them, and where running something settles a question, run it. The `check.sh` subcommands in `CLAUDE.md` are the ones CI uses.

Find everything first, then filter once. While reading, collect every concern at any severity rather than deciding as you go whether one is worth mentioning: judging severity while looking suppresses real findings. Then make one pass over the list and drop only what you could not substantiate, keeping anything real however small. Filter on "is this true", never on "is this important enough".

Say so plainly when the change is simply good. A review that manufactures objections to look thorough is worth as little as one that rubber-stamps.

Work through the diff yourself. Delegate to a subagent only when the diff is genuinely too large to hold in one reading, and then split it by area so each subagent owns a different part rather than re-reviewing the same code. One is usually enough. Do not spawn a subagent to double-check a finding you already have.

## Also confirm

**It fixes the issue it claims to.** Find the issue from a closing keyword in the PR body (`fixes #N`, `closes #N`, `resolves #N`) and read the issue itself, not the PR's description of it. Distinguish fixing it from fixing part of it, fixing something adjacent, and not addressing it at all. With no issue linked, say what problem the PR appears to solve and whether it is worth carrying.

**It is right for this repository.** Judge against this repo's rules rather than generic taste. `CLAUDE.md` governs architecture principles, code conventions, and the PR rules; the language section for whatever it touches applies; a skill covering that area applies too. Watch for the repo-wide bans CI does not always catch on a PR: inline lint escapes, comment blocks over 8 lines, banned Python accessors, `.unwrap()` on fallible Rust paths, `any` in TypeScript.

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

**Verdict:** `NOISE`, `BUGGED`, or `MERGE`, then a dash and the one thing that decided it. Judge the diff and nothing else. CI is not your business: a red check is on the PR page already, it says nothing about whether the change is right, and a sound change with a formatting failure is still `MERGE`.

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
