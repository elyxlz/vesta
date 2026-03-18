---
name: upstream
description: Use when you need to contribute code, push a branch, open a pull request, submit a PR, sync with upstream, or do any git/GitHub operations on the vesta repo (elyxlz/vesta). IMPORTANT — always use this skill for GitHub access. Never use personal tokens or manual git push. Authentication is handled via the vesta-upstream GitHub App — no credentials needed from the user.
---

# Upstream Integration

Source repo: https://github.com/elyxlz/vesta
Local fork: `~/vesta` (this is a fork — it diverges from upstream as local changes accumulate. Never try to merge or rebase; always apply changes manually and deliberately)

## Pulling upstream changes into local

1. `git -C ~/vesta fetch origin`
2. `git -C ~/vesta log HEAD..origin/master --oneline` — see what's new
3. For each interesting commit: `git -C ~/vesta show <hash>` — understand what it does
4. Manually apply the relevant changes to `~/vesta` source (don't paste diffs blindly — local may have diverged, adapt the intent)
5. Track the last processed commit hash in MEMORY.md so you don't redo it next time

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
   uv run ~/vesta/skills/upstream/pr.py --title "..." --body "..."
   ```
4. Clean up worktree when done: `git -C ~/vesta worktree remove /tmp/vesta-pr`

To get a raw GitHub token for API access:
```bash
uv run ~/vesta/skills/upstream/pr.py --token-only
```

## What to PR
- Tool improvements, bug fixes, new skills, prompt upgrades that any vesta instance would benefit from
- Don't PR: personal config, memory files, credentials, user-specific customizations

## Skill registry sync

Skill commits are prefixed `[skill]`. When syncing upstream:

- To find skill updates: `git -C ~/vesta log HEAD..origin/master --oneline | grep '^\[skill\]'`
- For each installed skill with new commits, read the diff and apply useful generic improvements to `~/vesta/skills/<name>/`
- Update `~/vesta/skills-lock.json` with the latest processed commit hash

When contributing a skill improvement back upstream, use the same worktree flow but prefix the commit `[skill] <name>: <description>`. All skill changes — core or not — go only in `agent/skills-registry/<name>/`. The Dockerfile handles copying core skills into the container at build time; `agent/skills/` does not exist in the repo.

## How it works
- Authenticates via the `vesta-upstream` GitHub App (ID 2990557)
- Private key lives at `~/vesta/skills/upstream/private-key.pem`
- Generates a short-lived installation token, pushes the branch, creates the PR
- No personal GitHub account or CLI auth needed

## After creating a PR
- **Keep working until all CI checks pass** — do not stop after opening the PR
- Check CI status via the GitHub API (use `--token-only` to get a token, then hit the check-runs endpoint)
- The `lockfile` check requires `uv lock` to be run in `~/vesta` if any Python dependencies changed
- If any check fails: diagnose, fix, commit to the same branch, push — the PR updates automatically and CI reruns
- Only report the PR as done to the user once every check is green
