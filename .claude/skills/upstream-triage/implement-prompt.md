# Implementing a decided fix from the upstream triage

You implement ONE work item from the triage report the orchestrator names (`~/vesta-triage/<date>-upstream-triage.md`). Read that file's section(s) for your item first: the **Problem**, **Clean fix**, and **Decision** lines are the spec. The Decision line wins over anything else. Do not widen scope beyond it.

## Repo rules (read before touching code)

1. Read `AGENTS.md` at the repo root in full. It is the bar: Architecture Principles, code conventions, testing strategy, Pull requests section. Key rules you will hit: one fix per root cause; minimize global state; banned accessors (`getattr`, dict `.get()` fallback, `hasattr`); no `TODO/FIXME/TEMPORARY/XXX`; comments capped at 8 lines and a long comment is a code smell; **anything under `agent/` states mechanism and constraint, never what changed or the incident behind it** (that goes in the commit and PR body); Markdown under `agent/` has no em or en dashes; Python is functional (no classes with methods); type everything.
2. Before editing anything under `agent/`, invoke the `vesta-prompt-guide` skill and apply it.
3. Match surrounding style exactly: one-line paragraphs in SKILL.md files (no hard wrapping), existing test file conventions, existing naming.

## Mechanics

- The main checkout stays clean. Work in a worktree:
  ```bash
  git fetch origin -q
  git worktree add ../vesta-wt/<branch> -b <branch> origin/master
  ```
  Branch names: `fix/<scope>-<short>` or `docs/<scope>-<short>`. For a bot branch you are amending, check that branch out instead (`git worktree add ../vesta-wt/<name> origin/<bot-branch>`, then `git checkout -b <bot-branch>` tracking it).
- Read the superseded PRs (`gh pr view <N>`, `gh pr diff <N>`) for their problem statements, evidence, and any tests worth carrying over. Carry over good tests verbatim where the Decision says so.
- Write the failing test first when the item is a behavior fix, then make it pass.
- Verify: the skill's own suite (`cd agent/skills/<name>/cli && uv run pytest -q`, or `cd agent && uv run pytest tests/<file> -q` for `agent/tests`), `uvx ruff format` + `uvx ruff check` from `agent/` on changed Python (the repo config lives there; `uv run ruff` is not in that project's env), `./check.sh guards` from the worktree root, `bash -n` on changed shell. If `shellcheck` is not installed, say so in the report. Markdown under `agent/`: `grep -rnP '\x{2014}|\x{2013}' <changed files>` must be empty.
- Commit: Conventional Commit subject (`type(scope): imperative, lowercase, no period`), body explains the why and names the superseded PRs. End the message with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  ```
- Push: `git push -u origin <branch>` (for a bot branch: `git push origin HEAD:<bot-branch>`).
- Open the PR (skip for a bot-branch amendment; the PR exists):
  ```bash
  body="$(git rev-parse --git-dir)/pr-body.md"   # this worktree's private git dir
  gh pr create --base master --title "<same as commit subject>" --body-file "$body"
  ```
  Write the body file in your own worktree's git dir, never a shared scratch path: several agents run at once and a shared path gets overwritten between your write and `gh`'s read. Re-read the PR body after creating it.
  Body structure: `## Problem` (one paragraph, from the superseded PRs, credit them by number), `## Change` (bullets, what and why at the design level), `## Evidence` (test names, counts, commands run), then a final line `Supersedes #N, #M.` No `fixes`/`closes` keywords for PRs. If a superseded PR body had `fixes #<issue>`, carry that line over verbatim on its own line.
- Then `gh pr checks <n> --watch` until done. If CI fails, fix on the branch and push again. Report a PR done only when checks are green.
- **Do NOT merge. Do NOT close or comment on any other PR or issue.** That happens centrally.

## Report back (concise)

- Branch, PR number and URL, CI state.
- Files changed with +/- counts.
- What you did differently from the Decision line, if anything, and why (a wrong assumption in the spec, a master change since triage). If the spec's premise turned out false, stop and report instead of improvising.
- Anything you noticed that is out of scope but worth a follow-up (one line each).
