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
git -C ~ diff --stat "agent-v$VER"..HEAD -- agent/ ':(exclude)agent/core/**'
```

Walk the list and, for each changed/added file, decide with gate 1 below: generalizable → file it; user-specific → leave it local. Common finds: a hook, script, or SKILL.md improvement built for one task that any instance would want.

**Go WITHIN each file, not just file-by-file.** The `--stat` view tempts you to sort at the whole-file level ("MEMORY.md is personal → skip", "a new skill → file"), but a file that is mostly user-specific almost always carries general improvements buried inside it: a restart SKILL.md that mixes a user-specific service list (local) with a hard-won "a migration prompt is a boot turn, restore daemons first" note (general); a skill doc where a *mechanism* is general but the specific names/addresses are personal. So for every changed file, `git -C ~ diff "agent-v$VER"..HEAD -- <file>` and read the actual hunks: split each into the general part (the rule, the mechanism, the fix) and the user-specific part (names, addresses, paths, one person's texting quirks). Upstream the general part with the personal part stripped or genericized; leave only the truly personal remainder local. The unit of contribution is the improvement, not the file.

Two gotchas learned the hard way:
- **Diff against the `agent-vX.Y.Z` tag, NOT `upstream/master`.** Vesta serves the workspace as a *subset* of the full monorepo (no `core/`, `tests/`, frontend), so a raw diff against `upstream/master` is polluted with thousands of phantom "deletions" for files that aren't in your workspace at all. The tag is your exact stock baseline, so its diff is purely your real changes.
- **A local-only file that never existed upstream is the easiest thing to miss.** If you built a whole hook/script locally, there's nothing to "sync", so it silently never gets contributed. The sweep catches exactly these.

## Before filing (REQUIRED)

Four gates before opening a worktree.

**0. Does it already exist? (grep FIRST, in the natural layer.)** Before building or upstreaming any mechanism, `grep -rn` the codebase for an existing implementation, and look in the layer where it would naturally live, not just one spot. It's easy to check only one directory (e.g. a `hooks/` dir), conclude "not upstream yet", and file a redundant PR that duplicates a check already wired into a channel CLI or core. Duplicated logic is a smell that the solution isn't the right one. So: search by the FEATURE name across all skills + core, not by where you assume it lives; if it exists, improve that one, don't add a second.

**1. Is it worth filing?** The rule for everything below: **generalizable goes upstream, user-specific stays local.** Everything is upstreamable unless it's personal information or super niche to one user; if a change would help any vesta instance, it belongs upstream. Concretely:
- Bug fixes in agent code, skills, or prompts
- New skills (strip personal config first) (can be specific skills, they are opt in for new vestas)
- Prompt or SKILL.md or MEMORY.md improvements
- **Personality / voice improvements** (the `personality` SKILL.md shared rules, the `presets/*.md` preset files, the bubble_lint hook). These ship with every vesta, so a sharpened rule that isn't glued to one user's specifics benefits everyone.
- Infrastructure or tooling improvements

**2. Issue, PR, or both?**
- You have a fix: **PR + issue**. The PR **body** must contain a closing keyword + issue number (`fixes #N` / `closes #N` / `resolves #N`) on its own line. GitHub only auto-closes the linked issue on merge when that keyword is in the PR body, so without it the issue stays open after the PR merges and someone has to close it by hand. Put it in the body, NOT the commit message (per CLAUDE.md, commits carry no closing keywords). `upstream-pr --body "...fixes #N"` is enough.
- You don't have a fix yet: **issue only**.

**3. Strip personal information.** Upstream is public, so the user must not be identifiable: never file personal config, their own memory content, credentials, or user-specific customizations (a rule that names the user or their contacts, a preset drifted to one person's texting quirks). Describe the pattern in general terms ("agent claimed inability to access calendar when google skill was installed"), not the specific instance ("user asked about tuesday's meeting with..."). When in doubt, leave it out.

## Shaping the change (REQUIRED)

When you add functionality to a skill that already ships a CLI (`cli/`), fold it in as a **subcommand of that CLI**, reusing its shared auth/client/helpers; do not drop a standalone script beside it. One entry point per skill: a loose script re-implements auth, escapes the skill's tests, and rots. Ship the subcommand with a test under `cli/tests/` and document it in `SKILL.md` alongside the others.

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

The home `~` workspace ignores everything outside `agent/`, and local commits diverge from upstream; never branch from local HEAD. Always use a clean worktree off `origin/master`.

1. **Create the worktree:**
   ```bash
   git -C ~ fetch origin
   git -C ~ worktree add /tmp/vesta-pr -b feature/<name> origin/master
   ```

2. **File the linked issue first** (if doing PR + issue), so the PR can reference it. See "Filing an issue" below.

3. **Apply changes** to `/tmp/vesta-pr`.

4. **Commit and submit:**
   ```bash
   cd /tmp/vesta-pr
   git add <files> && git commit -m "<description>"
   upstream-pr --title "..." --body "..."
   ```

5. **Clean up:** `git -C ~ worktree remove /tmp/vesta-pr`

6. **Wait for CI to pass.** Get a token with `upstream-pr --token-only`, then poll the check-runs endpoint. If a check fails: diagnose, fix, commit to the same branch, push, the PR updates automatically. The `lockfile` check requires `uv lock` in `~/agent` if Python deps changed.

Only report a PR as done once every CI check is green.

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

## Formatting Python before pushing

Before pushing changed `.py`, format from `~/agent` so the pinned ruff and config match CI's `agent-tests`: `cd ~/agent && uv run --project core ruff format <path> && uv run --project core ruff check <path>`. Run `uv run --project core ruff` from that dir, never `uvx ruff` or another cwd: those ignore the lock (`agent/core/uv.lock`) and config (`agent/ruff.toml`) and can fail CI's `--check` on otherwise-correct code.
