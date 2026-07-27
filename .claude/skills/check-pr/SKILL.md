---
name: check-pr
description: >
  Use when the user asks to check a PR, review a PR, sanity-check a pull request,
  ask whether a PR is correct or ready, or run "check-pr <number>". Also runs
  automatically on newly opened PRs. Reads the issue the PR claims to fix, judges
  whether it actually fixes it, checks it against this repository's conventions,
  and reports with a merge verdict. Read only: never pushes, merges, or closes.
---

# Check a PR

Answer one question about a pull request: should this be merged? Read only. Never push a commit, never merge, never close, never edit the PR. Changing the PR is `polish-pr`'s job, and it runs only when a human asks for it.

## What to check

**1. Does it fix the issue it claims to fix?**

Find the issue from a closing keyword in the PR body (`fixes #N`, `closes #N`, `resolves #N`). Read the issue itself, not just the PR's description of it, then decide whether this change resolves it. Distinguish clearly between fixing the issue, fixing part of it, fixing something adjacent, and not addressing it at all.

When no issue is linked, say what problem the PR appears to solve and whether it is worth carrying. A change with no traceable motivation is worth flagging on its own.

**2. Is it right for this repository?**

Judge against this repo's rules rather than generic taste. `CLAUDE.md` governs architecture principles, code conventions, brand voice, and the PR rules; the language section for whatever it touches applies; a skill covering that area applies too. Watch specifically for the repo-wide bans that CI does not always catch on a PR: inline lint escapes, comment blocks over 8 lines, banned Python accessors, `.unwrap()` on fallible Rust paths, `any` in TypeScript.

**3. Is it actually correct?**

Read the code paths the change touches. Do not trust the description, the comments, or the tests' names. Where running something settles a question, run it: the check subcommands in `CLAUDE.md` are the same ones CI uses. Look for the cases the author did not write a test for.

**4. Is it in a mergeable state?**

CI green, no conflicts, not draft, and scoped to one concern.

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
