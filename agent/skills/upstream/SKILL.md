---
name: upstream
description: Upstream elyxlz/vesta GitHub ops through gh: PRs, issues, CI, API reads.
---

# Upstream (CLI: upstream)

Contribute back to `elyxlz/vesta`. `upstream gh <args>` is the `gh` CLI with auth (the
vesta-upstream GitHub App) and the repo (`GH_REPO=elyxlz/vesta`) injected into the child
process, so everything you know about `gh` works from any directory with no token handling:

```bash
upstream gh pr view 2116
upstream gh pr checks 2116
upstream gh issue list
upstream gh api repos/elyxlz/vesta/pulls/2116/files
```

Three calls are intercepted and carry extra behavior:

- `upstream gh pr create --title T --body B [--head BR] [--base master] [--adopt]`:
  validates the title, refuses to force-push a branch whose commits are all another
  agent's (`--adopt` takes it over deliberately), pushes with auth in env, appends the
  attribution footer (`Submitted by **<agent>** on vesta v<version>`), then creates the
  PR, or force-pushes the branch of the existing one, whose title and body stay as first
  filed (edit those with `upstream gh pr edit`).
- `upstream gh issue create --title T --body B`: validates the title, appends the same
  footer, creates the issue. The App cannot comment on or edit an issue after posting
  (403), so the body must be complete at create time.
- `upstream gh pr list --mine [--state open|closed|all] [--limit N]`: the PRs this agent
  wrote. Every PR here is authored by `vesta-upstream[bot]`, so ownership lives in commit
  authors (`<agent-name> (vesta)`) and plain `gh pr list` cannot answer "which are mine".
  Run it before touching any branch you did not create this session; never take an
  author name you saw in a log as your own commit author.

Titles are `type(scope): description`: type one of feat, fix, refactor, perf, docs, test,
ci, chore, style, build; scope lowercase; description imperative, lowercase start, no
trailing period. Nonconforming titles are refused with the rule that broke.

`upstream token` prints a live installation token for a raw call the wrapper cannot
express. Never run it bare: capture it in the same command that uses it
(`TOKEN=$(upstream token)`), because stdout persists into your event store. If a token
does land in history, scrub it: `~/agent/skills/dream/scripts/redact_secrets.sh` then
`--scrub <event id>`.

## Setup

```bash
uv tool install --editable ~/agent/skills/upstream/cli
```

## Discovering what to file (nightly, in the dream's Upstream phase)

Your workspace `~` is a git repo whose stock baseline is the tag `agent-vX.Y.Z` matching
your version. Sweep the full contribution surface:

```bash
VER=$(grep '^version = ' ~/agent/core/pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
git -C ~ status --porcelain -- agent/          # untracked files (a local-only script is invisible to diff)
git -C ~ diff --stat "agent-v$VER" -- agent/   # tracked changes vs stock
```

Neither command takes `..HEAD` (that excludes the working tree, where your edits live) and
the diff runs against the tag, never `upstream/master` (the workspace is a subset of the
monorepo, so a master diff drowns in phantom deletions). Go WITHIN each file: a mostly
personal file usually carries a general improvement worth extracting. Upstream the general
part; leave the personal remainder local.

## Before filing (REQUIRED)

- **Does it already exist?** `grep -rn` the codebase for the mechanism first, by feature
  name across all skills and core. Improve the existing one; never add a second.
- **Your box is a stale snapshot.** Any claim about what upstream does must be checked
  against `upstream/master` (`git -C ~ show upstream/master:<path>`), never your local
  copy, or the PR is a revert dressed as a fix.
- **One file, one PR.** List your open PRs and their files before opening; two changes to
  one file belong in one PR. Do not check what other agents filed; duplicates are cheap
  confirmation.
- **Issue, PR, or both?** Fix in your workspace: PR + issue, with `fixes #N` on its own
  line in the PR body (never the commit). Problem in `agent/core/` (read-only): issue
  only, with cause, file, line, and the fix you would make. No fix yet: issue only.
- **Strip the story.** Agent-facing files state mechanism and constraint, never what
  changed or the incident behind it; that goes in the commit and PR body.
- **Strip personal information.** Upstream is public: no names, addresses, credentials,
  or one user's quirks. Describe the pattern, not the instance.

## Creating a PR

Never branch from local HEAD; use a clean worktree off `upstream/master`:

```bash
git -C ~ remote set-url upstream https://github.com/elyxlz/vesta.git 2>/dev/null || \
  git -C ~ remote add upstream https://github.com/elyxlz/vesta.git
git -C ~ fetch upstream
git -C ~ worktree add /tmp/vesta-pr -b feature/<name> upstream/master
cd /tmp/vesta-pr   # apply changes, commit
upstream gh pr create --title "fix(skills/x): ..." --body "...fixes #N"
```

Branch off `upstream/master` only, never `agent-upstream` (a standalone snapshot with no
master ancestry; the shared-history guard catches it). Wait for CI green
(`upstream gh pr checks <n>`); fix failures on the same branch and re-run
`upstream gh pr create` from the worktree, after fetching and rebasing onto the branch's
remote tip, since the push is a force push. A bare `git push upstream` has no credentials
by design; the wrapper is the authenticated path. Keep the worktree until the local apply
below is verified, then `git -C ~ worktree remove /tmp/vesta-pr`. Report a PR done only
when every check is green.

## Apply the fix locally too

A merged PR reaches you at the next release, so apply the workspace fix to your own tree
in the same pass. Verify by diff, one-directionally (every hunk the PR added must be in
your local file; a `-` line may be your user's personalization, which stays):

```bash
git -C ~ diff --no-index ~/agent/skills/<skill>/<path> /tmp/vesta-pr/agent/skills/<skill>/<path>
```

Never `cp` the whole file over your local one. Finish with the skill's own tests
(`cd ~/agent/skills/<name>/cli && uv run pytest`) and the ruff pass below.

## Formatting before pushing

Run `./check.sh guards` IN THE WORKTREE: it is ruff plus repo conventions (lint escapes,
comment-length cap of 8 lines, import cycles, shellcheck). Format Python from `~/agent`
so the pinned ruff and config match CI: `cd ~/agent && ruff format <path> && ruff check <path>`.
Markdown under `agent/` must contain no em or en dashes:
`grep -rnP '\x{2014}|\x{2013}' <paths>` must be empty; instruct subagents about this up
front, since models reach for those dashes by default.
