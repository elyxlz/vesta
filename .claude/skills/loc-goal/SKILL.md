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

SCOPE: production AND test code. Go beyond dead code and surface dedup into architecture: single sources of truth, fewer aliases and less indirection, smaller code stacks, and justified external-library swaps (prefer libs already in the tree; update the lockfile if you add one). Tests are in scope too: cut their line count via shared fixtures, parametrization, and removing genuinely redundant cases, but NEVER weaken or remove an assertion or shrink what behavior is covered. A slimmed test must still fail if the behavior it guards breaks.

METHOD: parallel per-area git worktrees, one subagent per area, each verifying against that area's ./check.sh before committing. Keep the deep-reduction PRs OPEN as drafts and keep pushing to them; do NOT merge the deep-reduction PRs. Land genuine fixes (regressions, guards) as their own normal PRs. Cap each wave to a few agents and target the largest still-unmined file rather than re-sweeping.

NET-NEGATIVE INVARIANT: every committed change must delete net lines AND read cleaner. Reject net-neutral or net-positive changes; a helper whose definition plus comments offset its dedup is not a win. Do not manufacture negatives by golfing comments away.

CONVERGENCE: when a surface returns about zero net twice, mark it floored and stop re-mining it. When every surface is floored and both draft PRs are green, the goal is satisfied for now: pause and report. Resume a surface only when git log shows substantial new code has landed there. Converge honestly rather than churn; recognizing the irreducible floor IS the goal, not infinite spinning.

GUARDRAILS (these caused real bugs before):
- "Zero importers" is not "dead": before deleting a file, grep for implicit consumers (sync or mirror scripts such as scripts/sync-dashboard.sh, codegen, a registry feeding another tree).
- Merge current origin/master into each branch before measuring net or merging up. A diff that shows unrelated files as deleted means the branch is stale: rebase it.
- Off-limits: apps/web/src/components/ui (the canonical shadcn registry, mirrored 1-to-1 into the dashboard skill), anything marked intentional or do-not-delete in code, and the [Fill in...] personalization stubs.
- Charters CI enforces: no em or en dashes and no " - " prose separator in user-visible prose (SKILL.md, SPA copy, emails, legal); the dashboard-sync check must stay 1-to-1.

ESCALATION: bold restructurings that would delete real lines but cannot be proven behavior-safe go to a GitHub issue for approval, not a PR. If a large file is unreducible only because it has no tests, propose a small smoke-test PR first rather than a blind refactor.

Run waves of agents continuously across both repos, never stop chasing the irreducible, but stop when honest (floored) rather than churn.
```
