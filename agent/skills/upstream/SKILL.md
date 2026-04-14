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

Sync against **release tags**, not master. Use `$VESTA_VERSION` to know your current version.

### Steps

1. **Commit all local work:**
   Everything must be committed before syncing. Stage and commit all changes on your local branch:
   ```bash
   cd ~/vesta
   git add agent/
   git status
   ```
   If there are changes:
   ```bash
   git commit -m "local: <describe what changed>"
   ```
   If the working tree is already clean, continue.

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
   If there are conflicts, git will stop and list them.

4. **Resolve any conflicts:**
   For each conflicted file:
   - Read the conflict markers
   - **Default to keeping upstream (theirs)** unless the local change is a meaningful customization
   - If unsure, show the user both versions and ask which to keep
   - After resolving: `git add <file>` then `git commit --no-edit`

5. **Rebuild affected services:**
   - If dashboard files changed: rebuild and restart dashboard
   - If voice/tasks/stocks code changed: restart those services
   - If Python deps changed (`pyproject.toml`): `cd ~/vesta/agent && uv sync`

6. **Verify:** Check that services are running (`screen -ls`), test key endpoints.

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
