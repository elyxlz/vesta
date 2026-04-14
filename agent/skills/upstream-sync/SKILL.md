---
name: upstream-sync
description: Sync local agent code with new upstream releases. Use when checking for updates, merging release tags, or resolving merge conflicts with upstream vesta.
---

# Upstream Sync

Merge new vesta releases into your local branch. Sync against **release tags**, not master.

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

2. **Fetch tags and check for updates.**
   ```bash
   git -C ~/vesta fetch origin --tags --prune --prune-tags
   CURRENT=$(git -C ~/vesta describe --tags --abbrev=0 2>/dev/null || echo "none")
   LATEST=$(git -C ~/vesta tag --sort=-v:refname | grep '^v' | head -1)
   echo "Current: $CURRENT, Latest: $LATEST"
   ```
   If `$LATEST == $CURRENT`, stop -- already up to date.

3. **Merge the release tag.**
   ```bash
   git -C ~/vesta merge "$LATEST" --no-edit
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

5. **Verify.** `git describe --tags --abbrev=0` should show `$LATEST` and `git status` should be clean.

## Branch model

Your branch (named `$AGENT_NAME`) starts from the release tag you were deployed on. All local work is committed here. Merging release tags brings in upstream changes while preserving your customizations.

```
v0.1.132 (tag)
  * local commits
  * merge v0.1.133
  * more local commits
  * merge v0.1.134
```

View local customizations vs upstream: `git diff <latest-tag>..$AGENT_NAME`
