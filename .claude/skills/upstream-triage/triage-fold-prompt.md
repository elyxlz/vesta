You triage one slice of an epic branch (`<EPIC_BRANCH>`, PR #<EPIC_PR>) on this repo, checked out on master and clean, with `origin/master` and `origin/<EPIC_BRANCH>` fetched. The epic folded closed PRs filed by autonomous agents ("vesta agents") running inside user containers, without reviewing them. The agents see real problems in production, but their context is full of user work, so their fixes are often short-sighted: a bandaid at the symptom layer, a second mechanism beside one that already exists, new state where existing state already encodes the fact, a defensive guard stacked on an unfound root cause, or a large script where a small one would do. Your job is to tell the good fixes from the bandaids, per folded PR, and to name the clean fix when the PR's fix is not it.

The epic branch may be far behind master. Anything it changes may already be solved, moved, or obsoleted on master. Always compare against CURRENT master.

READ-ONLY. Do not edit files, do not check out branches, do not comment on GitHub, do not create worktrees. Only `gh pr view`, `gh api`, `git log/show/diff/blame` and reading files on master.

## Procedure

1. Read `AGENTS.md`'s Architecture Principles section. These are the bar. Pay special attention to: elegance/subtraction, one fix per root cause, deep modules, minimize global state, design errors out of existence, "anything under agent/ never describes a previous design", comments cap of 8 lines, banned accessors (getattr/.get()/hasattr), no `TODO/FIXME/TEMPORARY` markers, `LEGACY(remove-when: ...)` for transitional code.
2. Apply the Clean-fix lens from `.claude/skills/check-pr/SKILL.md` step 5 to every folded PR in your slice.
3. `gh pr view <EPIC_PR> --json body --jq .body` for the fold notes on your slice (conflict resolutions, review findings applied).
4. For each folded PR in your slice: `gh pr view <N> --json title,body` for the original problem statement and evidence. If it says `fixes #M`, `gh issue view M`.
5. Read the epic's diff for your paths: `git diff origin/master...origin/<EPIC_BRANCH> -- <paths>`. This is the change as it would land.
6. Read the surrounding code ON MASTER: the whole file each diff touches, its callers, and grep for any existing mechanism on master that already covers part of the problem. Also `git log --oneline origin/<EPIC_BRANCH>..origin/master -- <paths>` to see what master changed in those files since the fold: the problem may be solved or the surface gone.
7. Verify every claim in each PR body and in the fold notes against the actual diff (tests claimed vs tests present, behavior claimed vs code).

## Answer, per folded PR, in this exact structure (max ~250 words per PR)

**PR <N>: <title>**
- **Problem (real?)**: one sentence in your own words; is the evidence credible; does it still exist on master today?
- **Root cause and layer**: where the cause sits; is the fix at that layer or at a symptom layer?
- **Fix quality**: principles broken, with file:line pointers into the epic diff. Existing mechanism it duplicates or ignores. Size relative to the problem. Story-telling in agent/ files.
- **Clean fix**: the minimal right change, concretely, with an estimated size. If the PR is already the clean fix, say so.
- **Verdict**: MERGE / MERGE-WITH-NITS (list them) / REWRITE (real problem, materially different clean fix) / CLOSE (not real, already solved on master, duplicate, belongs in a personal workspace not upstream) / HUMAN (a product decision must come first; state it).
- **Confidence**: high / medium / low, and the one thing that would change your mind.

End with a **Slice summary**: which folded PRs to keep as-is, keep with nits, rewrite, or drop, and whether the slice's files conflict with anything on master.
