---
name: check-pr
description: >
  Use when the user asks to check a PR, review a PR, sanity-check a pull request,
  ask whether a PR is correct or ready, or run "check-pr <number>". Also runs
  automatically on newly opened PRs. Use it whenever the question is whether a
  change should be merged. Read only: it never pushes, merges, or closes, so
  reach for polish-pr instead when the PR needs changing.
---

# Check a PR

Critique a pull request's diff and the solution behind it, and answer one question: should this be merged? Read only. Never push a commit, never merge, never close, never edit the PR. Changing the PR is `polish-pr`'s job, and it runs only when a human asks for it.

You are not here to confirm the change works. Assume the description is optimistic and that the author stopped looking once it passed. Your value is the objection nobody else raised.

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

Post one comment. Engineers read it, not markers: it is a bug list and a verdict, not an essay.

The whole comment is a one-line verdict plus one bullet per finding. Nothing else. **80 words is a normal length. Past 150 you are padding.**

Each finding is **one sentence**: `file:line`, what breaks, what triggers it. Two only when the trigger genuinely needs it.

Never write any of these:

- a paragraph narrating your review ("I audited the claim that...", "Both mutation claims reproduce...")
- a list of what you checked that turned out fine, in any form
- a restatement of the PR description or the issue
- hedging on a finding you already decided to report

`NOT YET` means right in substance, blocked on something mechanical like CI or a conflict.

<example>
Fixes #412.

- `core/loops.py:88` deletes the notification file before the send is confirmed, so a failed send loses the message.
- `core/loops.py:120` catches bare `Exception` around the whole batch, so one bad notification drops the rest.

Verdict: NOT YET, the delete ordering drops messages on send failure, two-line fix.
</example>

<example>
Fixes #1529, in one place rather than twelve edits.

- `groups.go:84`, `chat_ops.go:124` return false after the remote write landed, so both now exit 1 when the WhatsApp side succeeded.
- `link.go:245` decodes `SocketResponse` separately and did not get the new rule, so a `success`-carrying command routed through it would lose the body.

Verdict: MERGE once the vestad jobs land.
</example>

Judge the change on its merits even when you wrote the code yourself, and say `DO NOT MERGE` when you believe it. A verdict that always says MERGE is worth less than no verdict.

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
