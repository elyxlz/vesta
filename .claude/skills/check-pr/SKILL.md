---
name: check-pr
description: >
  Use when the user asks to check a PR, review a PR, sanity-check a pull request,
  ask whether a PR is correct or ready, or run "check-pr <number>". Also runs
  automatically on newly opened PRs. Critiques the diff and the solution behind
  it, attacks the change rather than confirming it, checks it fixes the issue it
  claims to and matches this repository's conventions, and reports with a merge
  verdict. Read only: never pushes, merges, or closes.
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

Verify rather than trust. Read the code paths the diff touches, and where running something settles a question, run it. The `check.sh` subcommands in `CLAUDE.md` are the ones CI uses.

When the diff is large enough that one reading will miss things, spawn subagents in parallel, each attacking from a different angle (correctness, failure modes, conventions, the issue it claims to fix) and each told to refute the change rather than approve it. Report only what survives that: a finding you could not substantiate is noise, and noise teaches the reader to stop reading you.

Say so plainly when the change is simply good. A review that manufactures objections to look thorough is worth as little as one that rubber-stamps.

## Also confirm

**It fixes the issue it claims to.** Find the issue from a closing keyword in the PR body (`fixes #N`, `closes #N`, `resolves #N`) and read the issue itself, not the PR's description of it. Distinguish fixing it from fixing part of it, fixing something adjacent, and not addressing it at all. With no issue linked, say what problem the PR appears to solve and whether it is worth carrying.

**It is right for this repository.** Judge against this repo's rules rather than generic taste. `CLAUDE.md` governs architecture principles, code conventions, and the PR rules; the language section for whatever it touches applies; a skill covering that area applies too. Watch for the repo-wide bans CI does not always catch on a PR: inline lint escapes, comment blocks over 8 lines, banned Python accessors, `.unwrap()` on fallible Rust paths, `any` in TypeScript.

**It is mergeable.** CI green, no conflicts, not draft, scoped to one concern.

## Reporting

Post one comment. Lead with what matters rather than a walkthrough of the diff: a reader who merges on your word should not need to open the files. Findings that change the merge decision come first, and anything you verified empirically is worth stating as verified.

Close with a verdict line:

```
Verdict: MERGE | DO NOT MERGE | NOT YET
```

One sentence of reasoning after it. `NOT YET` is for a PR that is right in substance but blocked on something mechanical, CI or a conflict, so the reader knows the difference between "wrong" and "wait".

Judge the change on its merits even when you wrote the code yourself, and say `DO NOT MERGE` when you believe it. A verdict that always says MERGE is worth less than no verdict.

When the PR would benefit from the simplify and tidy pass that `polish-pr` does, say so in one line and name the skill, so a maintainer can ask for it. Do not run it yourself: it pushes commits, and that is the maintainer's call.

Nobody asked for this check, so close the comment by saying how to ask for the next thing. Keep it to a couple of lines under a `---` rule: mentioning `@vestabot` in a comment on the PR is what reaches you, name the two or three things worth asking for here (re-checking after new commits, running `polish-pr`, fixing red CI), and say that only maintainers can trigger you so a drive-by contributor is not left waiting on a reply that will never come.
