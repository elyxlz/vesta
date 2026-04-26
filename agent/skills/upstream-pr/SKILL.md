---
name: upstream-pr
description: Upstream elyxlz/vesta GitHub ops: branches, PRs, issues, CI, API.
---

# Upstream PR

Push contributions back to `elyxlz/vesta`. Authentication is handled by the `vesta-upstream` GitHub App, no personal tokens needed. PRs are always cut from `origin/master`, never from `$VESTA_UPSTREAM_REF` or local HEAD.

## Before filing (REQUIRED)

Three gates before opening a worktree.

**1. Is it worth filing?** Push upstream only what would benefit any vesta instance:
- Bug fixes in agent code, skills, or prompts
- New skills (strip personal config first)
- Prompt or SKILL.md improvements
- Infrastructure or tooling improvements

Never file: personal config, memory files, credentials, user-specific customizations.

**2. Issue, PR, or both?**
- You have a fix: **PR + issue**.
- You don't have a fix yet: **issue only**.

**3. Strip personal information.** Upstream is public; the user must not be identifiable. No names, contact details, private context, or specifics tied to the user or their data. Describe the pattern in general terms ("agent claimed inability to access calendar when google skill was installed"), not the specific instance ("user asked about tuesday's meeting with..."). When in doubt, leave it out.

## Attribution (REQUIRED)

Every PR and every issue must carry the agent name and vesta version, so maintainers know which agent on which version hit the bug or proposed the change.

- Agent name: `$AGENT_NAME`
- Vesta version: `$VESTA_UPSTREAM_REF` (e.g. `v0.1.148` in release builds, a branch name in dev)

`pr.py` automatically appends `Submitted by **<name>** on <version>` to PR bodies. For **issues**, append the same footer to the body yourself:

```
---
Submitted by **$AGENT_NAME** on `$VESTA_UPSTREAM_REF`
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
   uv run ~/agent/skills/upstream-pr/pr.py --title "..." --body "..."
   ```

5. **Clean up:** `git -C ~ worktree remove /tmp/vesta-pr`

6. **Wait for CI to pass.** Get a token with `pr.py --token-only`, then poll the check-runs endpoint. If a check fails: diagnose, fix, commit to the same branch, push, the PR updates automatically. The `lockfile` check requires `uv lock` in `~/agent` if Python deps changed.

Only report a PR as done once every CI check is green.

## Filing an issue

Get a token with `pr.py --token-only`, then POST to the GitHub Issues API. The title should name the pattern, not the specific instance. The body must include the attribution footer (see "Attribution").

## pr.py reference

```bash
# Create a PR (auto branch, base=master)
uv run ~/agent/skills/upstream-pr/pr.py --title "fix: ..." --body "..."

# Custom branch and base
uv run ~/agent/skills/upstream-pr/pr.py --title "..." --branch my-branch --base master

# Short-lived GitHub API token (for issues, check-runs, PR status)
uv run ~/agent/skills/upstream-pr/pr.py --token-only
```
