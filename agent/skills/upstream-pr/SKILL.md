---
name: upstream-pr
description: Upstream elyxlz/vesta GitHub ops: branches, PRs, issues, CI, API.
---

# Upstream PR

Push contributions back to `elyxlz/vesta`. Authentication is handled by the `vesta-upstream` GitHub App, no personal tokens needed.

## Setup

```bash
uv tool install --editable ~/agent/skills/upstream-pr/cli
```

## Discovering what to file (run this every night, in the dream's Upstream phase)

Don't wait to stumble on things worth upstreaming: sweep for them. Your workspace (`~`) is a git repo whose stock baseline is the tag `agent-vX.Y.Z` matching the version you run. Diffing your branch against that tag surfaces **everything you've changed or added on top of stock**, i.e. the full contribution surface, in one command:

```bash
VER=$(grep '^version = ' ~/agent/core/pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
git -C ~ status --porcelain -- agent/                                    # untracked and uncommitted
git -C ~ diff --stat "agent-v$VER" -- agent/ ':(exclude)agent/core/**'   # committed, vs stock
```

**Both commands are needed, and neither takes a `..HEAD`.** `TAG..HEAD` compares two commits, so it excludes the working tree, where an agent's edits live until something commits them; and when a release tag points at `HEAD`, that range is empty by construction and the sweep reports "nothing to upstream" every night. `git diff` also never lists untracked files, so a skill or script created locally is invisible to it. `git status --porcelain` is the half that sees both.

Walk the list and, for each changed/added file, decide with gate 1 below: generalizable → file it; user-specific → leave it local. Common finds: a hook, script, or SKILL.md improvement built for one task that any instance would want.

**Go WITHIN each file, not just file-by-file.** The `--stat` view tempts you to sort at the whole-file level ("MEMORY.md is personal → skip", "a new skill → file"), but a file that is mostly user-specific almost always carries general improvements buried inside it: a restart SKILL.md that mixes a user-specific service list (local) with a hard-won "a migration prompt is a boot turn, restore daemons first" note (general); a skill doc where a *mechanism* is general but the specific names/addresses are personal. So for every changed file, `git -C ~ diff "agent-v$VER" -- <file>` (no `..HEAD`, same reason as above) and read the actual hunks: split each into the general part (the rule, the mechanism, the fix) and the user-specific part (names, addresses, paths, one person's texting quirks). Upstream the general part with the personal part stripped or genericized; leave only the truly personal remainder local. The unit of contribution is the improvement, not the file.

Two gotchas learned the hard way:
- **Diff against the `agent-vX.Y.Z` tag, NOT `upstream/master`.** Vesta serves the workspace as a *subset* of the full monorepo (no `core/`, `tests/`, frontend), so a raw diff against `upstream/master` is polluted with thousands of phantom "deletions" for files that aren't in your workspace at all. The tag is your exact stock baseline, so its diff is purely your real changes.
- **A local-only file that never existed upstream is the easiest thing to miss.** If you built a whole hook/script locally, there's nothing to "sync", so it silently never gets contributed. `git diff` cannot see it; the `git status --porcelain` line above is the half that can.

## Before filing (REQUIRED)

Seven gates before opening a worktree.

**0. Does it already exist? (grep FIRST, in the natural layer.)** Before building or upstreaming any mechanism, `grep -rn` the codebase for an existing implementation, and look in the layer where it would naturally live, not just one spot. It's easy to check only one directory (e.g. a `hooks/` dir), conclude "not upstream yet", and file a redundant PR that duplicates a check already wired into a channel CLI or core. Duplicated logic is a smell that the solution isn't the right one. So: search by the FEATURE name across all skills + core, not by where you assume it lives; if it exists, improve that one, don't add a second.

**0a. Your box is a stale snapshot, so never let it be the evidence.** The tag diff above tells you what *you changed*; it says nothing about what is *currently true upstream*. Master moves on while a container stays on the version it was built with, so any hunk shaped as "the docs are wrong, here is what it really does" is a claim about master and has to be checked against master or `agent/core/`, never against the copy in `~/agent/skills/`. Otherwise the PR is not a fix, it is a revert of master to an older snapshot, and it reviews as a careful correction: only someone reading master sees what it does. Before filing one, `git -C ~ fetch upstream` then `git -C ~ show upstream/master:agent/skills/<skill>/SKILL.md`, and confirm anything you call missing really is (`git -C ~ ls-tree upstream/master agent/skills/<skill>/`). For a claim about behaviour, read the implementation: a flag lives in the CLI source, an endpoint's auth in core.

**0b. Do not touch one file from two open PRs.** Each branch is cut from master, so neither contains the other and both report mergeable; whichever lands second conflicts. Before opening one, list your own open PRs and their `files` via the API and check for overlap. Two changes to one file belong in one PR, or land the first and rebase the second onto it.

**1. Is it worth filing?** The rule for everything below: **generalizable goes upstream, user-specific stays local.** Everything is upstreamable unless it's personal information or super niche to one user; if a change would help any vesta instance, it belongs upstream. Concretely:
- Bug fixes in agent code, skills, or prompts
- New skills (strip personal config first) (can be specific skills, they are opt in for new vestas)
- Prompt or SKILL.md or MEMORY.md improvements
- **Personality / voice improvements** (the `personality` SKILL.md shared rules, the `presets/*.md` preset files, the bubble_lint hook). These ship with every vesta, so a sharpened rule that isn't glued to one user's specifics benefits everyone.
- Infrastructure or tooling improvements

**2. Issue, PR, or both?**
- You have a fix: **PR + issue**. The PR **body** must contain a closing keyword + issue number (`fixes #N` / `closes #N` / `resolves #N`) on its own line. GitHub only auto-closes the linked issue on merge when that keyword is in the PR body, so without it the issue stays open after the PR merges and someone has to close it by hand. Put it in the body, NOT the commit message (per CLAUDE.md, commits carry no closing keywords). `upstream-pr --body "...fixes #N"` is enough.
- You don't have a fix yet: **issue only**.

**2b. Strip the story before you file.** Anything under `agent/` never describes a previous design, because the agent reads it cold and a description of the old system reads as a description of the current one (see `AGENTS.md`). The file carries the mechanism and the constraint only. Cut from the diff: what the wording used to say, the date, the box or version it was found on, the incident behind it, and any "previously this did X". That material is worth keeping, in the commit message and the PR body, where a reviewer wants it anyway. Litmus: read the added prose as an agent who has never seen the bug, and cut every sentence that only makes sense if you have. Watch it hardest when the fix came out of a retrospective, since you arrive holding the narrative and the narrative is the part that must not ship.

**3. Strip personal information.** Upstream is public, so the user must not be identifiable: never file personal config, their own memory content, credentials, or user-specific customizations (a rule that names the user or their contacts, a preset drifted to one person's texting quirks). Describe the pattern in general terms ("agent claimed inability to access calendar when google skill was installed"), not the specific instance ("user asked about tuesday's meeting with..."). When in doubt, leave it out.

## Shaping the change (REQUIRED)

When you add functionality to a skill that already ships a CLI (`cli/`), fold it in as a **subcommand of that CLI**, reusing its shared auth/client/helpers; do not drop a standalone script beside it. One entry point per skill: a loose script re-implements auth, escapes the skill's tests, and rots. Document the subcommand in `SKILL.md` alongside the others, and ship it with a check the maintainer can actually run: `app-chat`, `whatsapp`, and `telegram` have CLI suites the repo's checks execute, so a test in that skill's `cli/tests/` runs there. Everywhere else `cli/tests/` is not wired into a check, so a test you add there is a test nobody runs: put it there anyway if the skill already has a suite, and either way state in the PR body exactly how you exercised the subcommand and what you saw.

## Attribution (REQUIRED)

Every PR and every issue must carry the agent name and vesta version, so maintainers know which agent on which version hit the bug or proposed the change.

- Agent name: `$AGENT_NAME`
- Vesta version: read from `~/agent/core/pyproject.toml`

`upstream-pr` automatically appends `Submitted by **<name>** on <version>` to PR bodies. For **issues**, append the same footer to the body yourself:

```
---
Submitted by **$AGENT_NAME** on vesta v<version>
```

## Creating a PR

The home `~` workspace ignores everything outside `agent/`, and local commits diverge from upstream; never branch from local HEAD. Always use a clean worktree off `upstream/master`.

1. **Create the worktree:**
   ```bash
   git -C ~ remote set-url upstream https://github.com/elyxlz/vesta.git 2>/dev/null || \
     git -C ~ remote add upstream https://github.com/elyxlz/vesta.git
   git -C ~ fetch upstream
   git -C ~ worktree add /tmp/vesta-pr -b feature/<name> upstream/master
   ```

   **The remote is `upstream`, and `~` may not have it yet.** A fresh box has no remotes at all: upstream sync's `fetch-upstream.sh` fetches the bind-mounted `/run/vesta-upstream/upstream.git` by path with explicit refspecs, so it never configures one, and `upstream` first appears when `upstream-pr` itself runs. So without the guard, `git -C ~ fetch upstream` on a box that has never opened a PR dies with `'upstream' does not appear to be a git repository`. The guard mirrors what `upstream-pr` does: `set-url` rewrites a stale URL (including one with a token embedded in it) back to the credential-free form, and when the remote is missing entirely, `add` creates it.

   Branch off `upstream/master` only, never `upstream/agent-upstream`: that ref is the standalone stock snapshot with no ancestry to master, and branching off it is the failure `ensure_shared_history` catches, a 422 "no history in common with master" at PR create.

2. **File the linked issue first** (if doing PR + issue), so the PR can reference it. See "Filing an issue" below.

3. **Apply changes** to `/tmp/vesta-pr`.

4. **Commit and submit:**
   ```bash
   cd /tmp/vesta-pr
   git add <files> && git commit -m "<description>"
   upstream-pr --title "..." --body "..."
   ```

5. **Clean up:** `git -C ~ worktree remove /tmp/vesta-pr`

6. **Wait for CI to pass.** Get a token with `upstream-pr --token-only`, then poll the check-runs endpoint. If a check fails: diagnose, fix, commit to the same branch, and re-run `upstream-pr` to update the PR. The `lockfile` check requires `uv lock` in `~/agent` if Python deps changed.

   **To add a commit to a PR that is already open, re-run `upstream-pr` from the worktree.** Recreate it on the existing branch (`git -C ~ worktree add /tmp/vesta-pr <existing-branch>`), commit, then run `upstream-pr --title "..." --body "..."` again: it force-pushes the branch and prints `PR already exists for this branch` rather than failing. Prefer this to opening a second PR for the same change.

   A bare `git push upstream <branch>` fails with `fatal: could not read Username for 'https://github.com'`, because the remote is deliberately credential-free. **Do not answer that by putting the token in the push URL.** The shell expands it, so a live token lands in argv, where any process on the box can read it off `ps`. `upstream-pr` keeps auth in the process environment for exactly this reason, pinned by `cli/tests/test_auth.py`, and it is already the authenticated path, so there is nothing to work around.

Only report a PR as done once every CI check is green.

## Commenting, and what the token can reach

**A PR comment succeeds and an issue comment does not, through the same endpoint.** The installation carries `pull_requests: write` and no `issues` permission, and GitHub routes PR comments through `/issues/:n/comments` as well, so the identical call succeeds or returns `403 Resource not accessible by integration` purely by what `:n` is:

| call | result |
|---|---|
| `POST /repos/elyxlz/vesta/issues` (create an issue) | 201 |
| `POST /issues/:n/comments` where `:n` is a **PR** | 201 |
| `POST /issues/:n/comments` where `:n` is an **issue** | 403 |
| `DELETE /issues/comments/:id` (a PR comment) | 204 |

So answer PR review feedback by commenting on the PR, which needs no workaround. Only a follow-up on a real issue has to become a new issue cross-referencing it (`Related to #N`); GitHub renders the backreference either way.

Treat that table as perishable: permissions belong to the installed App and change when it does. Posting a throwaway comment and deleting it measures the current answer in seconds, which beats trusting any written claim, this one included.

## Filing an issue

Get a token with `upstream-pr --token-only`, then POST to the GitHub Issues API. The title should name the pattern, not the specific instance. The body must include the attribution footer (see "Attribution").

## upstream-pr reference

```bash
# Create a PR (auto branch, base=master)
upstream-pr --title "fix: ..." --body "..."

# Custom branch and base
upstream-pr --title "..." --branch my-branch --base master

# Short-lived GitHub API token (for issues, check-runs, PR status)
upstream-pr --token-only
```

## Running a skill's tests

Each skill CLI is its own uv project, so run its tests from its own directory: `cd ~/agent/skills/<name>/cli && uv run pytest`. uv builds a local `.venv` there and leaves the engine venv at `~/agent/.venv` alone.

## Formatting Python before pushing

Before pushing changed `.py`, format from `~/agent` so the pinned ruff and config match CI's `guards` ruff pass: `cd ~/agent && ruff format <path> && ruff check <path>`. Plain `ruff` from that dir is the engine venv's pinned ruff (its bin leads your PATH), never `uvx ruff` or another cwd: those ignore the lock (`agent/core/uv.lock`) and config (`agent/ruff.toml`) and can fail CI's `--check` on otherwise-correct code.

## No em/en dashes in markdown

Before pushing changed prompt or skill `.md`, check for em dashes (U+2014) and en dashes (U+2013): `grep -rnP '\x{2014}|\x{2013}' <paths>` must be empty. CI's `test_no_em_or_en_dashes_in_prompt_and_skill_files` (`agent-tests`) fails the build on either character in those files; use commas, colons, or hyphens instead. Watch this especially when a subagent did the editing: instruct it up front, since models reach for those dashes by default. (This note avoids the literal characters for the same reason.)
