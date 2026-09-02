---
name: upstream
description: Contribute back to the Vesta project. Use to open a PR or an issue on elyxlz/vesta, watch its CI, or read anything in that repo through gh.
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

Search under-reports through this token: the App's permission set filters `/search/issues`
results, so an empty search is a lower bound, never proof an issue does not exist; check a
known number with `upstream gh issue view <n>`.

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

The maintainer merges a small fix at the right layer the same day. A fix that adds state,
a script, a flag, or a config format waits weeks and is usually rewritten, because the
clean fix is visible from the maintainer's full checkout and not from a box. These checks
are what separate the two.

- **Does it already exist?** `grep -rn` the codebase for the mechanism first, by feature
  name across all skills and core. Improve the existing one; never add a second.
- **Your box is a stale snapshot.** Any claim about what upstream does must be checked
  against `upstream/master` (`git -C ~ show upstream/master:<path>`), never your local
  copy, or the PR is a revert dressed as a fix.
- **Find the fact before adding state.** If the fix adds a variable, file, marker, timer,
  flag, env var, or config format, first name the thing on `upstream/master` that already
  holds that fact: a marker the same handler writes, a cache entry, a helper's return
  value, an artifact's mtime. Read the whole module and its callers, not the failing line.
  When that thing exists, the fix reads it; new state beside it is the shape that gets
  rewritten.
- **Fix the producer, not the line.** A guard in front of the failing line (`if value:`)
  treats one symptom. Follow the value to where it was produced and fix it there, once.
  If a second guard elsewhere seems necessary, the cause is still unfound.
- **Copy the neighbours' guards.** When adding an entry to a list of rules (a regex, a
  threshold, a column, a probe), read what the sibling entries carry (a case anchor, a
  digit lookahead, a `LEGACY(` marker, a matching test fixture) and carry the same. The
  siblings encode the false positives already paid for.
- **Size is a design signal.** A fix over about 40 lines, a new script, a new flag, or a new
  config format is a design decision, not a fix. File an issue instead of the PR, with the
  cause, file, line, and the change you would make; the maintainer shapes it from the full
  tree. Two symptoms of one mechanism (a stale install and a stale build behind the same
  gate) are one fix and one PR, never two.
- **One file, one PR.** List your open PRs and their files before opening; two changes to
  one file belong in one PR. Search open PRs for your scope
  (`upstream gh pr list --state open --search "in:title <scope>"`); when one already names
  your problem, do not file a second: the maintainer keeps one fix per problem and closes
  the rest, so the duplicate costs a consolidation and adds nothing. Add your evidence as
  an issue if it is new.
- **Issue, PR, or both?** Fix in your workspace: PR + issue, with `fixes #N` on its own
  line in the PR body (never the commit). Problem in `agent/core/` (read-only): issue
  only, with cause, file, line, and the fix you would make. No fix yet: issue only.
- **Strip the story.** Agent-facing files state mechanism and constraint, never what
  changed or the incident behind it; that goes in the commit and PR body. A code comment
  states the rule in one line, with no date and no PR number; a comment that needs a
  paragraph means the code needs simplifying.
- **Strip personal information.** Upstream is public: no names, addresses, credentials,
  or one user's quirks. Describe the pattern, not the instance. A script that encodes your
  user's file names, language, headings, or box paths is workspace tooling: keep it local.
- **Evidence names what is in the diff.** Every test the PR body mentions exists in the
  diff by name, and the body pastes the run's count. A claim the diff does not contain is
  read as the behavior being untested, and it costs the PR its credibility.

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
