---
name: upstream-pr
description: Create PRs, issues, and contributions to the upstream elyxlz/vesta repo. Use for any GitHub operations -- pushing branches, creating PRs, checking CI status, or accessing the GitHub API.
---

# Upstream PR

Contribute improvements back to `elyxlz/vesta`. Authentication is handled by the `vesta-upstream` GitHub App -- no personal tokens needed.

## Attribution -- always required

Every PR and every issue you create must include your agent name and the vesta version you are running, so maintainers know which agent on which version hit the bug or proposed the change.

- Agent name: `$AGENT_NAME`
- Vesta version: `$VESTA_UPSTREAM_REF` (e.g. `v0.1.148` in release builds, a branch name in dev)

`pr.py` automatically appends `Submitted by **<name>** on <version>` to every PR body. For **issues**, there is no wrapper -- you must add the same footer to the body yourself:

```
---
Submitted by **$AGENT_NAME** on `$VESTA_UPSTREAM_REF`
```

## GitHub token

For any GitHub API call (issues, check-runs, PR status):
```bash
uv run ~/agent/skills/upstream-pr/pr.py --token-only
```
Returns a short-lived installation token.

## Creating a PR

In your normal **`~`** (home) agent workspace, `.gitignore` ignores **everything outside `agent/`** (only `agent/` and `.gitignore` are tracked there). Do not expect to commit monorepo paths from that tree.

Local code diverges from upstream, so never branch from local HEAD. Use a clean worktree from upstream master.

1. **Create a worktree:**
   ```bash
   git -C ~ fetch origin
   git -C ~ worktree add /tmp/vesta-pr -b feature/<name> origin/master
   ```

2. **Apply changes** to `/tmp/vesta-pr`. Only universal improvements -- no personal config, memory, or credentials.

3. **Create a GitHub issue first** (use `--token-only` for API access), then reference it in the PR. Include the attribution footer in the issue body (see "Attribution" above).

4. **Commit and submit:**
   ```bash
   cd /tmp/vesta-pr
   git add <files> && git commit -m "<description>"
   uv run ~/agent/skills/upstream-pr/pr.py --title "..." --body "..."
   ```

5. **Clean up:** `git -C ~ worktree remove /tmp/vesta-pr`

6. **Wait for CI to pass.** Check status via the GitHub API (`--token-only` for a token, then query the check-runs endpoint). If a check fails: diagnose, fix, commit to the same branch, push. The PR updates automatically. The `lockfile` check requires `uv lock` in `~/agent` if Python dependencies changed.

Only report a PR as done once every CI check is green.

## What to PR

If an improvement would benefit any vesta instance, it should be PR'd:
- Bug fixes in agent code, skills, or prompts
- New skills (strip personal config first)
- Prompt improvements, SKILL.md improvements
- Infrastructure or tooling improvements

Do not PR: personal config, memory files, credentials, user-specific customizations.

## pr.py reference

```
# Create a PR
uv run ~/agent/skills/upstream-pr/pr.py --title "fix: ..." --body "..."

# Custom branch name and base
uv run ~/agent/skills/upstream-pr/pr.py --title "..." --branch my-branch --base master

# Just get a GitHub API token
uv run ~/agent/skills/upstream-pr/pr.py --token-only
```
