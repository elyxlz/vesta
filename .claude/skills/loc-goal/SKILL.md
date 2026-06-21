---
name: loc-goal
description: >
  Use when the user wants the canonical LOC-reduction goal text, asks to "set the reduce-loc
  goal", "give me the loc goal", "the goal prompt", or wants to (re)start the incessant
  LOC-reduction loop across the vesta and vesta-cloud repos. The assistant cannot invoke /goal
  itself (it is a UI command), so this skill outputs the exact text for the user to paste.
---

# LOC-reduction goal

When this skill runs, output the fenced block below **verbatim** (do not paraphrase, summarize,
trim, or add to it), then tell the user in one line: paste it into the prompt to set the goal,
since `/goal` is a UI command the assistant cannot invoke itself. Nothing else.

```
/goal Incessantly reduce lines of code across BOTH repos (vesta at ~/Repos/vesta and vesta-cloud at ~/Repos/vesta-cloud) as much as genuinely possible, without changing functionality and without code golf, keeping code simple, understandable, clean, and elegant.

SCOPE: production AND test code. Go beyond dead code and surface dedup into architecture: single sources of truth, fewer aliases and less indirection, smaller code stacks, and justified external-library swaps (prefer libs already in the tree; update the lockfile if you add one). Tests are in scope too: cut their line count via shared fixtures, parametrization, and removing genuinely redundant cases, but NEVER weaken or remove an assertion or shrink what behavior is covered. Shortening or removing comments is a valid reduction: short code usually reads better, so delete comments that merely restate the code and keep only terse why-comments.

METHOD: parallel per-area git worktrees, one subagent per area, each verifying against that area's ./check.sh before committing. Keep the deep-reduction PRs OPEN as drafts and keep pushing to them; do NOT merge the deep-reduction PRs. Land genuine fixes (regressions, guards) as their own normal PRs. Cap each wave to a few agents and target the largest still-unmined file.

NET-NEGATIVE: every committed change must delete net lines AND read cleaner. Reject changes that only break even by adding helper or comment bulk. Behavior-locking tests you add to make a refactor safe are exempt from the count (they buy safety and coverage); the non-test code they let you refactor must still net-delete.

BOLD CHANGES: a restructuring that would delete real lines but is not obviously behavior-safe belongs IN the PR, not deferred. To do it safely: if the area lacks tests, first write tests that capture current behavior, confirm they pass on the unchanged code, do the refactor, then confirm the same tests still pass (before and after, locally). Commit the tests with the refactor. Never skip a real reduction because an area lacked tests; add the tests and proceed.

OUTSIDE THE BOX: when a surface looks exhausted, that is a signal to think differently, not to stop. Try a new angle: a larger restructuring (with before/after tests), an external library, a cross-cutting pattern shared within a crate or package, test-code slimming, comment trimming, or move to another surface. Do not declare convergence, do not pause, do not conclude the work is done.

GUARDRAILS (these caused real bugs before):
- "Zero importers" is not "dead": before deleting a file, grep for implicit consumers (sync or mirror scripts such as scripts/sync-dashboard.sh, codegen, a registry feeding another tree). Honor any do-not-delete or "may be used in future" marker in the code.
- Merge current origin/master into each branch before measuring net or merging up. A diff that shows unrelated files as deleted means the branch is stale: rebase it.
- Leave the [Fill in...] personalization stubs intact.
- Charters CI enforces: no em or en dashes and no " - " prose separator in user-visible prose (SKILL.md, SPA copy, emails, legal); the dashboard-sync check must stay 1-to-1.

Run waves of agents continuously across both repos. Never stop.
```
