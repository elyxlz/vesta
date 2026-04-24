---
name: upstream-pr
description: Upstream elyxlz/vesta GitHub ops: branches, PRs, issues, CI, API.
---

# Upstream PR

Contribute improvements back to `elyxlz/vesta`. Authentication is handled by the `vesta-upstream` GitHub App -- no personal tokens needed.

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

3. **Create a GitHub issue first** (use `--token-only` for API access), then reference it in the PR.

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
