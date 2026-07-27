---
name: polish-pr
description: >
  Use when the user asks to polish a PR, clean up a PR before merge, or run
  "polish-pr <number>". Takes ONE named PR and dispatches a single Opus,
  worktree-isolated agent to run four scoped passes over its diff: a code review
  (with fixes), a simplify pass, a prompt-quality sweep of any touched
  prompts/skills, and a CLAUDE.md staleness pass that corrects docs the PR
  falsified and adds a section when the PR introduces a CLAUDE.md-altitude
  surface. The agent then verifies with the relevant check.sh suites, pushes a
  single polish commit to the PR branch, and comments a summary. Never pushes if
  verification is red.
---

# Polish a PR

Take one PR from "the author's draft" to "reviewer-ready" in a single autonomous pass: review, simplify, prompt-quality, and CLAUDE.md freshness, then verify and push. The heavy work runs inside one Opus subagent in its own worktree; this orchestrator only triages the PR and relays the result.

Scope: exactly ONE PR, named by number (or branch). To polish several, invoke the skill once per PR.

## Orchestrator

1. **Resolve the PR.**
   ```
   gh pr view <N> --json number,title,headRefName,baseRefName,isDraft,author,mergeable,headRepositoryOwner
   ```
   Stop and report (do not dispatch) if the PR is a draft, or is from a fork (you cannot push to fork branches). Record the head branch and base branch.

2. **Dispatch one Opus agent.** Run the whole workflow in a single worktree-isolated subagent on Opus:
   ```
   Agent({
     subagent_type: "general-purpose",
     isolation: "worktree",
     model: "opus",
     description: "polish PR #<N>",
     prompt: <the "Agent workflow" and "Hard rules" sections below, verbatim,
              with PR number, title, head branch, and base branch filled in>,
   })
   ```
   The `isolation: "worktree"` gives the agent its own checkout, so it never dirties the main tree.

3. **Relay the report.** When the agent returns, surface its summary to the user unchanged: what each pass changed, whether it pushed, and any CLAUDE.md items it flagged rather than wrote. If it stopped without pushing (verify red or a fork/draft slipped through), relay the diagnosis.

## Agent workflow (what the Opus subagent does)

You are in your own worktree. Do everything here inside it.

1. **Check out the PR and scope the diff.**
   ```
   gh pr checkout <N>
   git fetch origin <base>
   git diff --name-only origin/<base>...HEAD
   ```
   That changed-file set drives every pass and the verify mapping. Do not touch files outside it except `CLAUDE.md` (pass 4 may edit the documenting file even though the PR did not).

2. **Pass 1, Review.** Run `/code-review high --fix` so it reviews the PR diff and applies the confirmed correctness and reuse findings to the working tree. Let it finish and land its edits before the next pass.

3. **Pass 2, Simplify.** Run `/simplify` over the changed code to apply simplification, reuse, efficiency, and altitude cleanups. Review comes first on purpose: do not polish code that pass 1 was about to rewrite.

4. **Pass 3, Prompt-quality sweep.** Only if the diff touches a prompt surface, and only over the changed lines. Prompt surfaces:
   - `agent/core/prompts/*.md`
   - `agent/skills/**/SKILL.md`, `agent/core/skills/**/SKILL.md`, `.claude/skills/**/SKILL.md`
   - `agent/core/migrations/*.md`
   - `agent/MEMORY.md`

   Invoke the `vesta-prompt-guide` skill and apply its best practices to the changed prompt lines only. `CLAUDE.md` is out of scope here; pass 4 owns it.

5. **Pass 4, CLAUDE.md freshness.** Read the final code (after passes 1 and 2) against the documenting prose. Covers the root `CLAUDE.md` and any nested `CLAUDE.md` in a directory the PR touched. Two jobs, both scoped to what the PR changed:
   - **Correct staleness the PR caused:** where the diff renames a module, moves a path, changes a flow, env var, command, or invariant that `CLAUDE.md` describes, fix the now-false prose. Never fix pre-existing inaccuracies the PR did not cause.
   - **Add a missing section only when the PR introduces a CLAUDE.md-altitude surface:** a new flow, plane, module, invariant, config surface, command, or subsystem that belongs in `CLAUDE.md` and is not there. "Altitude" is the bar: architecture-level, not a helper or an internal refactor. Slot it into the right existing section (Architecture / Key Flows / Commands / etc.), match the surrounding structure, and obey the file's own brand voice (no dash separators in prose, "Vesta" or they/them never "it/she", guardian-angel positioning). If it is borderline whether something warrants a section, do NOT write it: flag it in the report for the author to decide.

6. **Verify.** Map the changed top-level areas to `./check.sh` subcommands and run each, plus `guards` always:
   | Changed path | Suite |
   |---|---|
   | `agent/` | `./check.sh agent` |
   | `vestad/` | `./check.sh vestad` |
   | `apps/core/` | `./check.sh app-core` |
   | `apps/web/` | `./check.sh app-web` |
   | `apps/desktop/` | `./check.sh app-desktop` |
   | `apps/mobile/` | `./check.sh app-mobile` |
   | any change | `./check.sh guards` |

   If the change spans many areas, `./check.sh all` is the safe superset. Everything must pass. If a suite is red and fixing it is within polish's remit (a lint escape the sweep introduced, a broken import), fix it and re-run. If it is red for a reason outside polish's remit, STOP: do not push, return the report path below.

7. **Ship or report.**
   - **Nothing changed** across all four passes: report that the PR is already clean. No commit, no push, no comment.
   - **Changed and green:** stage everything, make ONE commit `polish: review, simplify, docs sweep on #<N>` (adjust the subject to what actually changed), push to `<headBranch>`, then post a PR comment summarizing each pass: what review/simplify fixed, what the prompt sweep touched, what CLAUDE.md corrections or additions were made, and any borderline CLAUDE.md items you flagged rather than wrote. Return the same summary.
   - **Changed but verify red (outside remit):** do not push. Return the failing suite and diagnosis so the user decides.

## Hard rules

- **Never push to `master`**, and never `--force`/`--force-with-lease` push. Push only to the PR's own head branch, fast-forward.
- **Never touch `constitution.md`** or any user-authored immutable file.
- **Stay surgical.** Every changed line must trace to a review finding, a simplify cleanup, a prompt-guide fix, or a CLAUDE.md correction the PR caused. No taste-driven edits to code the PR did not touch. Do not rewrite the PR author's intent.
- **One commit per polish run.** Do not amend the author's commits, do not squash their history; add a single new polish commit on top.
- **Verify gates the push.** A red suite that polish did not cause and cannot fix within its remit blocks the push, always report instead.
- **One PR only.** This skill does not fan out across the fleet of open PRs; that is `babysit-prs`.
