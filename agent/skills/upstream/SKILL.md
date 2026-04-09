---
name: upstream
description: Use when you need to contribute code, push a branch, open a pull request, submit a PR, sync with upstream, or do any git/GitHub operations on the vesta repo (elyxlz/vesta). IMPORTANT — always use this skill for GitHub access. Never use personal tokens or manual git push. Authentication is handled via the vesta-upstream GitHub App — no credentials needed from the user.
---

# Upstream Integration

Source repo: https://github.com/elyxlz/vesta
Local fork: `~/vesta` (this is a fork — it diverges from upstream as local changes accumulate. Never try to merge or rebase; always apply changes manually and deliberately)

## Path mapping

The upstream repo nests all agent code under an `agent/` prefix. Locally, those same files live at the repo root. Always translate paths when syncing:

| Upstream (GitHub)               | Local (`~/vesta`)          |
|---------------------------------|----------------------------|
| `agent/skills/whatsapp/cli/`    | `skills/whatsapp/cli/`     |
| `agent/skills/<name>/SKILL.md`  | `skills/<name>/SKILL.md`   |
| `agent/prompts/MEMORY.md`       | `prompts/MEMORY.md`        |
| `agent/<anything>`              | `<anything>`               |

**Rule**: strip `agent/` when pulling upstream → local. Add `agent/` when pushing local → upstream.

When running `git diff` or `git log` against upstream, always scope to `agent/` and mentally map the paths. When copying files into a PR worktree (`/tmp/vesta-pr`), place them under `agent/`.

## Pulling upstream changes into local

Sync against **GitHub releases**, not individual master commits. Releases are the stable, intentional milestones — master commits are noisy work-in-progress.

1. `git -C ~/vesta fetch origin --tags --prune --prune-tags`
2. Find the latest release tag: `git -C ~/vesta tag --sort=-v:refname | head -5` (or `gh release list` via `--token-only` + API)
3. Compare the last processed release (tracked in MEMORY.md) to the latest: `git -C ~/vesta log <last-tag>..<latest-tag> --oneline -- agent/`
4. Only look at changes under `agent/`
5. For each interesting commit in the range: `git -C ~/vesta show <hash>` — understand what it does
6. Manually apply the relevant changes to `~/vesta` source (don't paste diffs blindly — local may have diverged, adapt the intent)
7. Track the last processed **release tag** (e.g. `v0.4.2`) in MEMORY.md so you don't redo it next time

If no new release exists since the last processed tag, there's nothing to sync — don't crawl master.

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

When syncing upstream, also check for skill updates under `agent/skills/` — scoped to the same release range:

- For each installed skill (`ls ~/vesta/skills/`) check for commits in `<last-tag>..<latest-tag>` touching `agent/skills/<name>/`: `git -C ~/vesta log <last-tag>..<latest-tag> --oneline -- agent/skills/<name>/`
- Read the diff and apply useful generic improvements to `~/vesta/skills/<name>/`
- The single release tag in MEMORY.md covers both core and skill syncs

When contributing a skill improvement back upstream, use the same worktree flow. All skill changes — core or not — go in `agent/skills/<name>/`.

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
