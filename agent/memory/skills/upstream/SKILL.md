---
name: upstream
description: Use when you need to contribute code, push a branch, open a pull request, submit a PR, sync with upstream, or do any git/GitHub operations on the vesta repo (elyxlz/vesta). IMPORTANT — always use this skill for GitHub access. Never use personal tokens or manual git push. Authentication is handled via the vesta-upstream GitHub App — no credentials needed from the user.
---

# Upstream Integration

Source repo: https://github.com/elyxlz/vesta

## Pulling changes
1. `git -C {repo_root} fetch origin && git -C {repo_root} log HEAD..origin/master --oneline` to see what's new
2. For interesting commits: `git -C {repo_root} show <hash> --stat` then `git -C {repo_root} show <hash>` for the full diff
3. Your local state may have diverged. Don't paste diffs blindly. Understand what each change was trying to do, then adapt it to where you are now
4. Track what you've processed so you don't redo it. Keep the last hash in MEMORY.md

## Pushing changes

From inside the vesta repo, on a feature branch:
```bash
uv run {skills_dir}/upstream/pr.py --title "What changed" --body "Why it changed"
```

To just get a token for raw API access:
```bash
uv run {skills_dir}/upstream/pr.py --token-only
```

## What to PR
- Skill improvements, bug fixes, new tools, prompt upgrades
- Don't PR user-specific config, personal data, or credentials

## How it works
- Authenticates via the `vesta-upstream` GitHub App (ID 2990557)
- Private key and script live in this skill directory
- Generates a short-lived installation token, pushes the branch, creates the PR
- No personal GitHub account or CLI auth needed

## After Creating a PR
- Monitor the PR until CI passes — don't just fire and forget
- Check CI status: `cd /root/vesta && gh pr checks <PR_NUMBER>`
- The `pr-validation` check requires a version bump in `agent/pyproject.toml` for any source code changes
- If CI fails, fix the issue, commit to the same branch, and push — the PR updates automatically
- Only report the PR as done to the user once CI is green
