---
name: upstream
description: Use when syncing with upstream releases, creating PRs, pushing branches, or doing any git/GitHub operations on elyxlz/vesta. Also use for GitHub API access (tokens, issues, check-runs).
---

# Upstream Integration

Authentication is handled by the `vesta-upstream` GitHub App — no personal tokens or manual git push. Use `pr.py` for all authenticated GitHub operations.

Source repo: `elyxlz/vesta` on GitHub
Local clone: `~/vesta` (sparse checkout, `agent/` only)

## Ownership split

Core code (`agent/src/vesta/`, `agent/pyproject.toml`, `agent/uv.lock`) is managed by vestad via read-only mounts. You cannot modify these files. vestad updates them by swapping the mounted code and restarting the container.

You own everything else: `agent/skills/`, `agent/prompts/`, `agent/memory/`, `.claude/`. These are tracked on your git branch and updated by merging release tags.

## Local branch model

Your branch (named `$AGENT_NAME`, e.g. `athena`) starts from the release tag you were deployed on. All local work is committed here.

```
v0.1.132 (tag) <-- branch starts here
  * local commits
  * merge: "Merge tag v0.1.133"
  * more local commits
  * merge: "Merge tag v0.1.134"
```

View local customizations vs upstream: `git diff <latest-tag>..$AGENT_NAME`

## Syncing upstream changes

Sync against **release tags**, not master.

1. **Commit all local work.**
   The merge will fail with uncommitted changes. Stage everything under `agent/`, excluding large/generated files:
   ```bash
   cd ~/vesta
   git add agent/ --ignore-errors
   git reset HEAD -- '*.bin' '*.onnx' '*.pt' '*.db' '*.sqlite' '*.mp3' '*.mp4' '*.wav' '*.zip' '*.tar.gz' '**/node_modules' '**/dist' '**/.venv' '**/__pycache__'
   git status
   ```
   Commit if there are staged changes. Add untracked large files to `.gitignore`.
   Repeat until `git status` is clean. Do not proceed with uncommitted work.

2. **Fetch tags and check for updates.**
   ```bash
   git -C ~/vesta fetch origin --tags --prune --prune-tags
   CURRENT=$(git -C ~/vesta describe --tags --abbrev=0)
   LATEST=$(git -C ~/vesta tag --sort=-v:refname | grep '^v' | head -1)
   echo "Current: $CURRENT, Latest: $LATEST"
   ```
   If `$LATEST == $CURRENT`, stop — already up to date.

3. **Merge the release tag.**
   ```bash
   git -C ~/vesta merge "$LATEST" --no-edit
   ```
   If clean, skip to step 5.

4. **Resolve conflicts** using these rules:

   - **Vestad-managed paths** (`src/vesta/`, `pyproject.toml`, `uv.lock`): always accept upstream: `git checkout --theirs <file> && git add <file>`. These are read-only mounts — vestad controls the running version.
   - **Agent-owned paths you haven't customized**: accept upstream (`git checkout --theirs <file> && git add <file>`).
   - **Agent-owned paths you meaningfully customized** (SKILL.md you rewrote, config you tuned, skill code you modified): show the user both versions and ask how to combine. Do not auto-resolve.

   After all conflicts are resolved: `git commit --no-edit`

5. **Restart services** per `restart.md`.

6. **PR any improvements.** Review local changes since last sync (`git diff $LATEST..$AGENT_NAME`). If any are universal improvements, see "Creating a PR" below.

**Verify:** after the merge, `git describe --tags --abbrev=0` should show `$LATEST` and `git status` should be clean.

## Creating a PR

Local diverges from upstream, so never branch from local HEAD. Use a clean worktree from upstream master.

1. **Create a worktree:**
   ```bash
   git -C ~/vesta fetch origin
   git -C ~/vesta worktree add /tmp/vesta-pr -b feature/<name> origin/master
   ```

2. **Apply changes** to `/tmp/vesta-pr`. Only universal improvements — no personal config, memory, or credentials.

3. **Create a GitHub issue first** (use `--token-only` for API access), then reference it in the PR.

4. **Commit and submit:**
   ```bash
   cd /tmp/vesta-pr
   git add <files> && git commit -m "<description>"
   uv run ~/vesta/agent/skills/upstream/pr.py --title "..." --body "..."
   ```

5. **Clean up:** `git -C ~/vesta worktree remove /tmp/vesta-pr`

6. **Wait for CI to pass.** Check status via the GitHub API (`--token-only` for a token, then query the check-runs endpoint). If a check fails: diagnose, fix, commit to the same branch, push. The PR updates automatically. The `lockfile` check requires `uv lock` in `~/vesta/agent` if Python dependencies changed.

**Verify:** only report the PR as done once every CI check is green.

## What to PR

Upstreaming is your duty to the vesta community. If an improvement would benefit any vesta instance, it must be PR'd:
- Bug fixes, prompt improvements, skill code/SKILL.md improvements, new skills, agent code fixes
- New skills you built locally (strip personal config first)

Do not PR: personal config, memory files, credentials, user-specific customizations.

## GitHub token access

For any GitHub API call (issues, check-runs, etc.):
```bash
uv run ~/vesta/agent/skills/upstream/pr.py --token-only
```
Returns a short-lived installation token. No personal credentials needed.
