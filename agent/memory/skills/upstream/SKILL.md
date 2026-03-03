---
name: upstream
description: Use when you need to submit a PR to the upstream vesta repo (elyxlz/vesta). This skill handles authentication via a GitHub App and creates pull requests.
---

# Upstream PRs

Submit improvements back to https://github.com/elyxlz/vesta so all vesta instances benefit.

## Usage

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
