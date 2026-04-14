---
name: upstream
description: Use when you need to contribute code, push a branch, open a pull request, submit a PR, sync with upstream, or do any git/GitHub operations on the vesta repo (elyxlz/vesta). IMPORTANT, always use this skill for GitHub access. Never use personal tokens or manual git push. Authentication is handled via the vesta-upstream GitHub App, no credentials needed from the user.
---

# Upstream Integration

Source repo: https://github.com/elyxlz/vesta
Local clone: `~/vesta` with sparse checkout (`agent/` only)

## Repo layout

The upstream repo contains agent code under `agent/`, plus non-agent code (app/, cli/, vestad/). The agent reads directly from `agent/` at runtime, so git-tracked paths and runtime paths are identical.

**Sparse checkout** is enabled so only `agent/` is materialized. Non-agent files are ignored.

## Local branch

On first boot, the agent creates a branch named after itself (e.g. `athena`) starting from the release tag it was deployed on (`v$VESTA_VERSION`). All local customizations are committed to this branch. The branch never tracks or pushes to any remote.

```
v0.1.132 (tag) ← branch starts here
  → local: "add stocks skill"
  → local: "tweak dashboard config"
  → merge: "Merge tag v0.1.133"
  → local: "add reminder tests"
  → merge: "Merge tag v0.1.134"
```

To see all local customizations vs upstream: `git diff v0.1.134..$AGENT_NAME`

### First-time setup

If the local branch doesn't exist yet (fresh deploy or migration):
```bash
git -C ~/vesta fetch origin --tags --prune --prune-tags
git -C ~/vesta checkout -b "$AGENT_NAME" "v$VESTA_VERSION"
```

## Pulling upstream changes (sync)

Sync against **release tags**, not master. Use `$VESTA_VERSION` to know your current version. Your local branch already exists (created at first boot) — all local work must be committed to it before merging.

### Steps

1. **Commit all local work first:**
   The merge will fail if there are uncommitted changes. Stage and commit everything:
   ```bash
   cd ~/vesta
   git add agent/
   git status
   ```
   If there are uncommitted changes:
   ```bash
   git commit -m "local: <describe what changed>"
   ```
   Repeat until `git status` shows a clean working tree. Do not proceed with uncommitted work.

2. **Fetch and find latest release:**
   ```bash
   git -C ~/vesta fetch origin --tags --prune --prune-tags
   LATEST=$(git -C ~/vesta tag --sort=-v:refname | grep '^v' | head -1)
   echo "Current: v$VESTA_VERSION, Latest: $LATEST"
   ```
   If `$LATEST` matches `v$VESTA_VERSION`, there's nothing to sync. Stop here.

3. **Merge the release tag:**
   ```bash
   git -C ~/vesta merge "$LATEST" --no-edit
   ```
   If the merge completes cleanly, skip to step 5.

4. **Resolve conflicts:**
   If git reports conflicts, handle each file using these rules:

   **Small conflicts** (a few lines, clear what changed):
   - Accept the upstream (release) version of the conflicting lines
   - Then re-apply your local change on top if it's still relevant
   - `git add <file>`

   **Large conflicts** (whole sections rewritten, hard to untangle):
   - Take the entire upstream version of the file: `git checkout --theirs <file>`
   - `git add <file>`
   - After the merge is complete, review what local changes you lost (`git diff v$VESTA_VERSION..$AGENT_NAME -- <file>` shows your old customizations)
   - Re-implement your changes cleanly on top of the new upstream code in a separate commit

   **Conflicts in files you customized meaningfully** (SKILL.md you rewrote, config you tuned, skill code you modified):
   - Show the user both versions — your local version and the upstream version
   - Ask the user which parts to keep and how to combine them
   - Do not auto-resolve these without user input

   **MEMORY.md**: Always keep yours. `git checkout --ours agent/MEMORY.md && git add agent/MEMORY.md`

   After all conflicts are resolved:
   ```bash
   git commit --no-edit
   ```

5. **Rebuild affected services:**
   - If dashboard files changed: rebuild and restart dashboard
   - If voice/tasks/stocks code changed: restart those services
   - If Python deps changed (`pyproject.toml`): `cd ~/vesta/agent && uv sync`

6. **Verify:** Check that services are running (`screen -ls`), test key endpoints.

7. **PR any improvements:**
   After syncing, review what you changed locally since the last sync (`git diff $LATEST..$AGENT_NAME`). If any of those changes are universal improvements (bug fixes, prompt improvements, new skills, skill code improvements), PR them following the "Pushing local changes upstream" instructions below. See "What to PR" for what qualifies.

### What NOT to sync
- `agent/MEMORY.md` (yours is personal, never overwrite)
- Non-agent files (app/, cli/, Cargo, etc.) are handled by vestad

## Pushing local changes upstream (creating a PR)

Local diverges from upstream, so never branch from local HEAD for a PR. Instead:

1. Create a clean worktree from upstream master:
   ```bash
   git -C ~/vesta fetch origin
   git -C ~/vesta worktree add /tmp/vesta-pr -b feature/<name> origin/master
   ```
2. Manually apply only the universal changes (no personal config, memory, credentials) to `/tmp/vesta-pr`
3. Commit and submit:
   ```bash
   cd /tmp/vesta-pr
   git add ... && git commit -m "..."
   uv run ~/vesta/agent/skills/upstream/pr.py --title "..." --body "..."
   ```
4. Clean up worktree when done: `git -C ~/vesta worktree remove /tmp/vesta-pr`

To get a raw GitHub token for API access:
```bash
uv run ~/vesta/agent/skills/upstream/pr.py --token-only
```

## What to PR

**Upstreaming is mandatory** whenever you've made a genuine improvement. If it would benefit any vesta instance, it must be PR'd.

- Bug fixes, prompt improvements, skill code/SKILL.md improvements, new skills you've created, agent code fixes
- If you built a new skill locally, PR it (strip personal config first)
- Don't PR: personal config, memory files, credentials, user-specific customizations
- **Always create a GitHub issue first**, then reference it in the PR. Use `--token-only` to get a token for the GitHub API

## How it works
- Authenticates via the `vesta-upstream` GitHub App (ID 2990557)
- Private key lives at `~/vesta/agent/skills/upstream/private-key.pem`
- Generates a short-lived installation token, pushes the branch, creates the PR
- No personal GitHub account or CLI auth needed

## After creating a PR
- **Keep working until all CI checks pass.** Do not stop after opening the PR
- Check CI status via the GitHub API (use `--token-only` to get a token, then hit the check-runs endpoint)
- The `lockfile` check requires `uv lock` to be run in `~/vesta/agent` if any Python dependencies changed
- If any check fails: diagnose, fix, commit to the same branch, push. The PR updates automatically and CI reruns
- Only report the PR as done to the user once every check is green
