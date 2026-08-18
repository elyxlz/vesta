---
name: upstream
description: Upstream elyxlz/vesta GitHub ops: branches, PRs, issues, CI, API.
---

# Upstream (CLI: upstream)

Push contributions back to `elyxlz/vesta`. Authentication is handled by the `vesta-upstream` GitHub App, no personal tokens needed.

## Setup

```bash
uv tool install --editable ~/agent/skills/upstream/cli
```

## Discovering what to file (run this every night, in the dream's Upstream phase)

Don't wait to stumble on things worth upstreaming: sweep for them. Your workspace (`~`) is a git repo whose stock baseline is the tag `agent-vX.Y.Z` matching the version you run. Diffing your branch against that tag surfaces **everything you've changed or added on top of stock**, i.e. the full contribution surface, in one command:

```bash
VER=$(grep '^version = ' ~/agent/core/pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
git -C ~ status --porcelain -- agent/                                    # untracked files
git -C ~ diff --stat "agent-v$VER" -- agent/   # tracked changes, vs stock
```

**Both commands are needed, and neither takes a `..HEAD`.** `TAG..HEAD` compares two commits, so it excludes the working tree, where an agent's edits live until something commits them; and when a release tag points at `HEAD`, that range is empty by construction and the sweep reports "nothing to upstream" every night. `git diff` also never lists untracked files, so a skill or script created locally is invisible to it. `git status --porcelain` is the half that lists those.

Walk the list and, for each changed/added file, decide with gate 1 below: generalizable → file it; user-specific → leave it local. Common finds: a hook, script, or SKILL.md improvement built for one task that any instance would want.

**Go WITHIN each file, not just file-by-file.** The `--stat` view tempts you to sort at the whole-file level ("MEMORY.md is personal → skip", "a new skill → file"), but a file that is mostly user-specific almost always carries general improvements buried inside it: a restart SKILL.md that mixes a user-specific service list (local) with a hard-won "a migration prompt is a boot turn, restore daemons first" note (general); a skill doc where a *mechanism* is general but the specific names/addresses are personal. So for every changed file, `git -C ~ diff "agent-v$VER" -- <file>` (no `..HEAD`, same reason as above) and read the actual hunks: split each into the general part (the rule, the mechanism, the fix) and the user-specific part (names, addresses, paths, one person's texting quirks). Upstream the general part with the personal part stripped or genericized; leave only the truly personal remainder local. The unit of contribution is the improvement, not the file.

Two gotchas learned the hard way:
- **Diff against the `agent-vX.Y.Z` tag, NOT `upstream/master`.** Vesta serves the workspace as a *subset* of the full monorepo (no `core/`, `tests/`, frontend), so a raw diff against `upstream/master` is polluted with thousands of phantom "deletions" for files that aren't in your workspace at all. The tag is your exact stock baseline, so its diff is purely your real changes.
- **A local-only file that never existed upstream is the easiest thing to miss.** If you built a whole hook/script locally, there's nothing to "sync", so it silently never gets contributed. The `git status --porcelain` line above is what catches it.

## Before filing (REQUIRED)

Seven gates before opening a worktree.

**0. Does it already exist? (grep FIRST, in the natural layer.)** Before building or upstreaming any mechanism, `grep -rn` the codebase for an existing implementation, and look in the layer where it would naturally live, not just one spot. It's easy to check only one directory (e.g. a `hooks/` dir), conclude "not upstream yet", and file a redundant PR that duplicates a check already wired into a channel CLI or core. Duplicated logic is a smell that the solution isn't the right one. So: search by the FEATURE name across all skills + core, not by where you assume it lives; if it exists, improve that one, don't add a second.

**Do not check what other agents already filed upstream.** File yours even when a duplicate likely exists: duplicate filings confirm the bug independently, often carry different halves of the answer, and cost the maintainer one consolidation pass, while deferring to an open PR risks parking your fix behind one that is wrong or stalled. The only overlap you check is your own open PRs (gate 0b).

**0a. Your box is a stale snapshot, so never let it be the evidence.** The tag diff above tells you what *you changed*; it says nothing about what is *currently true upstream*. Master moves on while a container stays on the version it was built with, so any hunk shaped as "the docs are wrong, here is what it really does" is a claim about master and has to be checked against master or `agent/core/`, never against the copy in `~/agent/skills/`. Otherwise the PR is not a fix, it is a revert of master to an older snapshot, and it reviews as a careful correction: only someone reading master sees what it does. Before filing one, add the `upstream` remote and fetch it with the guarded form in "Creating a PR" step 1 (a box that has never opened a PR has no `upstream` remote, so a bare `git -C ~ fetch upstream` dies), then `git -C ~ show upstream/master:agent/skills/<skill>/SKILL.md`, and confirm anything you call missing really is (`git -C ~ ls-tree upstream/master agent/skills/<skill>/`). For a claim about behavior, read the implementation: a flag lives in the CLI source, an endpoint's auth in core.

**0b. Do not touch one file from two open PRs.** Each branch is cut from master, so neither contains the other and both report mergeable; whichever lands second conflicts. Before opening one, list your own open PRs and their `files` via the API and check for overlap. Two changes to one file belong in one PR.

**1. Is it worth filing?** The rule for everything below: **generalizable goes upstream, user-specific stays local.** Everything is upstreamable unless it's personal information or super niche to one user; if a change would help any vesta instance, it belongs upstream. Concretely:
- Bug fixes in agent code, skills, or prompts
- New skills (strip personal config first) (can be specific skills, they are opt in for new vestas)
- Prompt or SKILL.md or MEMORY.md improvements
- **Personality / voice improvements** (the `personality` SKILL.md shared rules, the `presets/*.md` preset files, the bubble_lint hook). These ship with every vesta, so a sharpened rule that isn't glued to one user's specifics benefits everyone.
- Infrastructure or tooling improvements

**2. Issue, PR, or both?**
- You have a fix in the workspace (`~/agent/skills/`, prompts, MEMORY.md structure): **PR + issue**. The PR **body** must contain a closing keyword + issue number (`fixes #N` / `closes #N` / `resolves #N`) on its own line. GitHub only auto-closes the linked issue on merge when that keyword is in the PR body, so without it the issue stays open after the PR merges and someone has to close it by hand. Put it in the body, NOT the commit message (per CLAUDE.md, commits carry no closing keywords). `upstream --body "...fixes #N"` is enough.
- The problem lives in `agent/core/`: **issue only**, however sure you are of the fix. Core is mounted read-only, so you cannot apply or run a core change on your box, and an untested engine PR costs more review than a precise issue. Describe the cause, the exact file and line, and the fix you would make; a maintainer lands it.
- You don't have a fix yet: **issue only**.

**2b. Strip the story before you file.** Anything under `agent/` never describes a previous design, because the agent reads it cold and a description of the old system reads as a description of the current one (see `AGENTS.md`). The file carries the mechanism and the constraint only. Cut from the diff: what the wording used to say, the date, the box or version it was found on, the incident behind it, and any "previously this did X". That material is worth keeping, in the commit message and the PR body, where a reviewer wants it anyway. Litmus: read the added prose as an agent who has never seen the bug, and cut every sentence that only makes sense if you have. Watch it hardest when the fix came out of a retrospective, since you arrive holding the narrative and the narrative is the part that must not ship.

**3. Strip personal information.** Upstream is public, so the user must not be identifiable: never file personal config, their own memory content, credentials, or user-specific customizations (a rule that names the user or their contacts, a preset drifted to one person's texting quirks). Describe the pattern in general terms ("agent claimed inability to access calendar when google skill was installed"), not the specific instance ("user asked about tuesday's meeting with..."). When in doubt, leave it out.

## Shaping the change (REQUIRED)

When you add functionality to a skill that already ships a CLI (`cli/`), fold it in as a **subcommand of that CLI**, reusing its shared auth/client/helpers; do not drop a standalone script beside it. One entry point per skill: a loose script re-implements auth, escapes the skill's tests, and rots. Document the subcommand in `SKILL.md` alongside the others, and ship it with a check the maintainer can actually run: `app-chat`, `whatsapp`, and `telegram` have CLI suites the repo's checks execute, so a test in that skill's `cli/tests/` runs there. Everywhere else `cli/tests/` is not wired into a check, so a test you add there is a test nobody runs: put it there anyway if the skill already has a suite, and either way state in the PR body exactly how you exercised the subcommand and what you saw.

## Attribution (REQUIRED)

Every PR and every issue must carry the agent name and vesta version, so maintainers know which agent on which version hit the bug or proposed the change.

- Agent name: `$AGENT_NAME`
- Vesta version: read from `~/agent/core/pyproject.toml`

`upstream` automatically appends `Submitted by **<name>** on <version>` to PR bodies. For **issues**, append the same footer to the body yourself:

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

   **The remote is `upstream`, and `~` may not have it yet.** A fresh box has no remotes at all: upstream sync's `fetch-upstream.sh` fetches the bind-mounted `/run/vesta-upstream/upstream.git` by path with explicit refspecs, so it never configures one, and the `upstream` remote first appears when the `upstream` command itself runs. So without the guard, `git -C ~ fetch upstream` on a box that has never opened a PR dies with `'upstream' does not appear to be a git repository`. The guard mirrors what the `upstream` command does: `set-url` rewrites a stale URL (including one with a token embedded in it) back to the credential-free form, and when the remote is missing entirely, `add` creates it.

   Branch off `upstream/master` only, never `upstream/agent-upstream`: that ref is the standalone stock snapshot with no ancestry to master, and branching off it is the failure `ensure_shared_history` catches, a 422 "no history in common with master" at PR create.

2. **File the linked issue first** (if doing PR + issue), so the PR can reference it. See "Filing an issue" below.

3. **Apply changes** to `/tmp/vesta-pr`.

4. **Commit and submit:**
   ```bash
   cd /tmp/vesta-pr
   git add <files> && git commit -m "<description>"
   upstream --title "..." --body "..."
   ```

5. **Wait for CI to pass.** Capture a token with `TOKEN=$(upstream --token-only)` (never bare, see "Handling the token"), then poll the check-runs endpoint. If a check fails: diagnose, fix, commit to the same branch, and re-run `upstream` to update the PR. The `lockfile` check requires `uv lock` in `~/agent` if Python deps changed.

   **To add a commit to a PR that is already open, re-run `upstream` from the worktree.** Recreate it on the existing branch (`git -C ~ worktree add /tmp/vesta-pr <existing-branch>`), and before committing anything, fetch and rebase onto the branch's remote tip: the re-run force-pushes your local copy, so any commits a maintainer or sibling added to the branch since your last push are silently discarded unless you picked them up first. Then commit and run `upstream --title "..." --body "..."` again: it force-pushes the branch and prints `PR already exists for this branch` rather than failing. Prefer this to opening a second PR for the same change.

   A bare `git push upstream <branch>` fails with `fatal: could not read Username for 'https://github.com'`, because the remote is deliberately credential-free. **Do not answer that by putting the token in the push URL.** The shell expands it, so a live token lands in argv, where any process on the box can read it off `ps`. `upstream` keeps auth in the process environment for exactly this reason, pinned by `cli/tests/test_auth.py`, and it is already the authenticated path, so there is nothing to work around.

6. **Apply the same fix to your local tree and check it against the branch.** See "Apply the fix locally too" below.

7. **Clean up, last:** `git -C ~ worktree remove /tmp/vesta-pr`

Keep the worktree until the end. Steps 5 and 6 both need it: CI fixes are committed in it, and it is what step 6 compares against. Removing it earlier means recreating it.

Only report a PR as done once every CI check is green.

## Apply the fix locally too

A merged PR reaches you at the next release; your user keeps hitting the bug until then. So apply any workspace fix to your own tree in the same pass, all of it, tests and lint refactors included, since a half-applied fix leaves the tree lint-red and unguarded. A local apply is a stopgap: maintainers edit and consolidate PRs before merging, so the released form can differ from what you applied, the next sync then conflicts on that file, and the released side wins, it is your own fix repaired.

Verify by diff instead of memory, at step 6 while the worktree exists:

```bash
# for each file the PR touched; if the worktree is gone, use the second form
git -C ~ diff --no-index ~/agent/skills/<skill>/<path> /tmp/vesta-pr/agent/skills/<skill>/<path>
git -C ~ show feature/<name>:agent/skills/<skill>/<path> | diff -u ~/agent/skills/<skill>/<path> -
```

Read it one-directionally: every hunk the PR added must be present verbatim in your local file. A `+` line is fix you have not applied, so apply it. A `-` line is either your user's personalization that gate 3 correctly kept out of the PR (leave it exactly where it is) or text the fix deleted and you did not (decide per hunk). Empty output is only right for a file carrying nothing personal; never chase it, and never `cp` the whole file over your local one: that deletes the personalization and blanks this very check. Finish with the skill's own gates locally (`cd ~/agent/skills/<name>/cli && uv run pytest`, plus the ruff pass from `~/agent`), and restart the daemon if the CLI is an editable install, since a running process serves the old code until then.

## Commenting, and what the token can reach

**A PR comment succeeds and an issue comment does not, through the same endpoint.** The installation carries `pull_requests: write` and no `issues` permission, and GitHub routes PR comments through `/issues/:n/comments` as well, so the identical call succeeds or returns `403 Resource not accessible by integration` purely by what `:n` is:

| call | result |
|---|---|
| `POST /repos/elyxlz/vesta/issues` (create an issue) | 201 |
| `POST /issues/:n/comments` where `:n` is a **PR** | 201 |
| `POST /issues/:n/comments` where `:n` is an **issue** | 403 |
| `DELETE /issues/comments/:id` (a PR comment) | 204 |
| `PATCH /issues/:n` (edit an **issue** body) | 403 |
| `PATCH /pulls/:n` (edit a **PR** body) | 200 |
| `GET /issues/:n` (read any issue) | 200 |

So answer PR review feedback by commenting on the PR, which needs no workaround. Only a follow-up on a real issue has to become a new issue cross-referencing it (`Related to #N`); GitHub renders the backreference either way.

**The same missing permission also means you cannot revise an issue after you post it.** Its body 403s on `PATCH` and its thread 403s on a comment, so an issue filed through this token is one shot: everything it needs to say, including the attribution footer, has to be in the body at create time. A PR is the opposite, since `PATCH /pulls/:n` succeeds, so a correction or late evidence can be edited into a PR body at any point. Use it: the body is the durable public claim about a change, so a wrong number left standing there outlives every later commit that quietly contradicts it.

**`/search/issues` is filtered by the same permission, so it under-reports issues rather than being wrong about them.** A query whose words appear in an issue can return only the PRs that quote those words, and `is:issue` does not restore the missing item, so a `0` or a PR-only result set through this token is not evidence that the issue does not exist. Reading it as evidence turns a permission boundary into a false claim about GitHub. Check an issue you know the number of with `GET /issues/:n`, which succeeds on a public repo, and treat search through this token as a lower bound.

Treat that table as perishable: permissions belong to the installed App and change when it does. Posting a throwaway comment and deleting it measures the current answer in seconds, which beats trusting any written claim, this one included.

## Filing an issue

Capture a token with `TOKEN=$(upstream --token-only)` (never bare, see "Handling the token"), then POST to the GitHub Issues API. The title should name the pattern, not the specific instance. The body must include the attribution footer (see "Attribution").

## Handling the token (REQUIRED)

`--token-only` writes a **live** GitHub App installation token to stdout, and your runtime persists tool output into the event store. So a bare `upstream --token-only` deposits a working credential into your own searchable history, where it outlives the request that needed it.

Always capture it into a shell variable in the same command that uses it, so the value never reaches stdout:

```bash
TOKEN=$(upstream --token-only)
curl -s -H "Authorization: token $TOKEN" https://api.github.com/repos/elyxlz/vesta/issues
```

To check only that the auth channel works, test the exit status, never the value:

```bash
upstream --token-only >/dev/null && echo "auth ok"
```

If a token does reach your history, scrub it: `~/agent/skills/dream/scripts/redact_secrets.sh` then `--scrub <event id>`.

## Whose PR is it? (check before you touch one)

**Every agent files through the same GitHub App, so `pull.user.login` is `vesta-upstream[bot]` on
every PR in this repo and tells you nothing.** The repo is shared by many vesta instances filing
concurrently, so the newest open PRs are usually a mix of several agents' work, and "it appeared
while I was awake" is not evidence it is yours. The only field that carries authorship is the
**commit author**, `<agent-name> (vesta)`, and the FIRST commit's author is who opened it.

```bash
upstream --mine              # PRs you opened, and separately ones you only pushed commits to
upstream --mine --state all --limit 60
```

Run this before a review sweep, before fixing CI on "your" PRs, and before pushing to any branch you
did not create in this session. Timing is not evidence: a PR that appeared while you were awake is
as likely to be a sibling's. When an author name does appear in a `git log` or `git show`, it is a
fact to check, never a name to set as your own commit author.

`upstream` refuses to push to a remote branch whose commits are all somebody else's (another
agent's or a human's), since the push is a **force** push and would discard their work. It also
refuses when the remote branch exists but cannot be read, rather than guessing; that refusal means
the network or auth is broken, so wait and retry, and never reach for `--adopt` to get past it.
Pass `--adopt` only on the ownership refusal, when taking over the named authors' branch is
genuinely what you mean.

The guard catches name collisions, not every overwrite: a branch you have commits on is yours to
push, and the force push replaces the remote with your local copy. So before re-running
`upstream` on an existing branch, fetch and rebase onto its remote tip first; a maintainer or
sibling may have pushed commits to it since your last push, and pushing without fetching silently
discards those.

If you do fix a sibling's broken PR, that is welcome, and say so in the body: what you changed, why
you touched it, and that they should revert freely. Never restate their evidence as yours, and
never "correct" a measurement with numbers from your own box; their box has different traffic,
different accounts and different history, so your count is not a check on theirs.

## upstream reference

```bash
# Create a PR (auto branch, base=master)
upstream --title "fix: ..." --body "..."

# Custom branch and base
upstream --title "..." --branch my-branch --base master

# Which of these PRs are actually yours
upstream --mine

# Take over a branch another agent started (force push, so this is deliberate)
upstream --title "..." --branch their-branch --adopt

# Short-lived GitHub API token (for issues, check-runs, PR status).
# Always capture it, never run bare: stdout is persisted into the event store.
TOKEN=$(upstream --token-only)
```

## Running a skill's tests

Each skill CLI is its own uv project, so run its tests from its own directory: `cd ~/agent/skills/<name>/cli && uv run pytest`. uv builds a local `.venv` there and leaves the engine venv at `~/agent/.venv` alone.

## Formatting Python before pushing

**Run `./check.sh guards` IN THE WORKTREE, not just ruff.** The `guards` job is ruff PLUS repo conventions ruff knows nothing about, so a ruff-clean file still fails CI: the one that bites most often is `comment block of N lines (max 8); simplify the code instead`, which fires on any run of consecutive `#` lines and is a standing trap when documenting a subtle regex or invariant. The guard is asking for a simplification, so take it: name the parts (`_DIGIT_RUN = ...`, `_SUFFIX = ...`) and give each its own short comment, rather than shortening one wall. `guards` also checks lint escapes, import cycles, shellcheck and the uv.lock. Two steps need tools a container may lack (shellcheck, rsync) and stop with a clear message; everything before them still runs, so it is worth running anyway.

Before pushing changed `.py`, format from `~/agent` so the pinned ruff and config match CI's `guards` ruff pass: `cd ~/agent && ruff format <path> && ruff check <path>`. Plain `ruff` from that dir is the engine venv's pinned ruff (its bin leads your PATH), never `uvx ruff` or another cwd: those ignore the lock (`agent/core/uv.lock`) and config (`agent/ruff.toml`) and can fail CI's `--check` on otherwise-correct code.

## No em/en dashes in markdown

Before pushing changed prompt or skill `.md`, check for em dashes (U+2014) and en dashes (U+2013): `grep -rnP '\x{2014}|\x{2013}' <paths>` must be empty. CI's `test_no_em_or_en_dashes_in_prompt_and_skill_files` (`agent-tests`) fails the build on either character in those files; use commas, colons, or hyphens instead. Watch this especially when a subagent did the editing: instruct it up front, since models reach for those dashes by default. (This note avoids the literal characters for the same reason.)
