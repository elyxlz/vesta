---
name: upstream-sync
description: Sync local agent code with upstream. Use when checking for updates, merging new releases or branch changes, or resolving merge conflicts with upstream vesta.
---

# Upstream Sync

Merge upstream changes into your local branch. The env var `$VESTA_UPSTREAM_REF` tells you what to sync against — it's a release tag in prod (e.g. `v0.1.132`) or a branch in dev (e.g. `feat/agent-source-dir`).

## Ownership

You own `agent/skills/`, `agent/prompts/`, `agent/MEMORY.md`, `.claude/`. These are tracked on your git branch.

Core code (`agent/src/vesta/`, `agent/pyproject.toml`, `agent/uv.lock`) is managed by vestad via read-only mounts. Always accept upstream for these paths during merges.

## Sync steps

1. **Commit all local work.** The merge will fail with uncommitted changes.
   ```bash
   cd ~/vesta
   git add agent/ --ignore-errors
   git reset HEAD -- '*.bin' '*.onnx' '*.pt' '*.db' '*.sqlite' '*.mp3' '*.mp4' '*.wav' '*.zip' '*.tar.gz' '**/node_modules' '**/dist' '**/.venv' '**/__pycache__'
   git status
   ```
   Commit if there are staged changes. Add untracked large files to `.gitignore`.
   Repeat until `git status` is clean.

2. **Fetch and check for updates.**
   ```bash
   git -C ~/vesta fetch origin "$VESTA_UPSTREAM_REF"
   CURRENT=$(git -C ~/vesta rev-parse HEAD)
   LATEST=$(git -C ~/vesta rev-parse FETCH_HEAD)
   echo "Current: $CURRENT, Latest: $LATEST"
   ```
   If `$CURRENT == $LATEST`, stop -- already up to date.

3. **Merge upstream.**
   ```bash
   git -C ~/vesta merge FETCH_HEAD --no-edit
   ```
   If clean, skip to step 5.

4. **Resolve conflicts** using these rules:

   - **Vestad-managed paths** (`src/vesta/`, `pyproject.toml`, `uv.lock`): always accept upstream.
     ```bash
     git checkout --theirs <file> && git add <file>
     ```
   - **Agent-owned paths you haven't customized**: accept upstream the same way.
   - **Agent-owned paths you meaningfully customized** (SKILL.md you rewrote, config you tuned, skill code you modified): show the user both versions and ask how to combine. Do not auto-resolve.

   After all conflicts are resolved: `git commit --no-edit`

5. **Verify.** `git status` should be clean.

## Branch model

Your branch (named `$AGENT_NAME`) starts from the upstream ref you were deployed on. All local work is committed here. Merging upstream brings in changes while preserving your customizations.

```
v0.1.132 (upstream ref)
  * local commits
  * merge upstream
  * more local commits
  * merge upstream
```

View local customizations vs upstream: `git diff FETCH_HEAD..$AGENT_NAME` (after a fetch)
