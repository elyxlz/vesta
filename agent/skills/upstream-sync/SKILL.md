---
name: upstream-sync
description: Sync local agent code with upstream vesta: updates, merges, conflicts.
---

# Upstream Sync

Bring your local workspace into order, checkpoint your current state on your branch, then merge upstream. The goal is to get your branch into a clean, easy-to-merge shape relative to `$VESTA_UPSTREAM_REF`: current local state committed first, then upstream integrated on top. The env var `$VESTA_UPSTREAM_REF` tells you what to sync against: a release tag in prod (e.g. `v0.1.132`) or a branch in dev (e.g. `feat/agent-source-dir`).

## Ownership

At `~` (repo root is `$HOME`), the git tree contains the full upstream repo to keep diffs clean, but sparse checkout limits what's on disk to `agent/` (minus bind-mounted paths) and `.gitignore`. Repo-root `.claude/` stays local and does not show up as untracked noise. Use `~/agent/.gitignore` for large or local-only files you discover during setup so `git status` ends up commit-ready.

You own `agent/skills/`, `agent/prompts/`, `agent/MEMORY.md`, `agent/.gitignore`, and repo-root `.claude/` (symlink / SDK layout) on disk; git commits focus on `agent/`.

Core code (`agent/core/`, `agent/pyproject.toml`, `agent/uv.lock`) is managed by vestad via read-only mounts, but merge conflicts there still need integration work if both sides carry meaningful behavior.

## Sync steps

1. **Normalize local state first.** If the workspace is not already in the expected shape, read and follow [SETUP.md](SETUP.md) before continuing. The goal is: branch `$AGENT_NAME`, working tree under `~/agent`, bulky local-only files ignored in `~/agent/.gitignore`, and current code ready to commit as one clean checkpoint before upstreaming.

2. **Commit all local work.** The merge will fail with uncommitted changes, and the checkpoint commit gives you a clean local base before you bring in upstream.

   First, check if the tree needs repair (existing agents may have stripped trees from before this fix):
   ```bash
   git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
   ROOT_ENTRIES=$(git -C ~ ls-tree --name-only HEAD 2>/dev/null | wc -l)
   UPSTREAM_ENTRIES=$(git -C ~ ls-tree --name-only FETCH_HEAD 2>/dev/null | wc -l)
   MISSING_COUNT=$(git -C ~ diff FETCH_HEAD HEAD --name-status 2>/dev/null | grep -c '^D' || echo 0)
   if [ "$ROOT_ENTRIES" -lt 5 ] || [ "$MISSING_COUNT" -gt 10 ]; then
     echo "Tree needs repair ($ROOT_ENTRIES root entries, $MISSING_COUNT files stripped) - restoring full upstream tree..."
     # Restore all files from upstream that are missing from our tree (no disk writes)
     git -C ~ ls-tree -r FETCH_HEAD | while IFS=$'\t' read mode_type_hash path; do
       [ -z "$(git -C ~ ls-tree HEAD -- "$path" 2>/dev/null)" ] && {
         mode=$(echo "$mode_type_hash" | awk '{print $1}')
         hash=$(echo "$mode_type_hash" | awk '{print $3}')
         git -C ~ update-index --add --cacheinfo "$mode,$hash,$path"
       }
     done
     git -C ~ commit -m "fix: restore full upstream tree (self-heal stripped branch)" --allow-empty
   fi
   ```

   Then proceed with the normal checkpoint:
   ```bash
   cd ~
   git add agent/ --ignore-errors
   git reset HEAD -- '*.bin' '*.onnx' '*.pt' '*.db' '*.sqlite' '*.mp3' '*.mp4' '*.wav' '*.zip' '*.tar.gz' '**/node_modules' '**/dist' '**/.venv' '**/__pycache__'
   # Safety: ensure no non-agent files are accidentally staged for deletion
   git diff --cached --name-only --diff-filter=D | grep -v '^agent/' | grep -v '^\.gitignore$' | xargs -r git reset HEAD -- 2>/dev/null || true
   git status
   ```
   Add untracked large files to `~/agent/.gitignore`. If there are staged changes, commit them with this exact message format:
   ```bash
   git -C ~ commit -m "chore: checkpoint local state before $VESTA_UPSTREAM_REF upstream sync"
   ```
   If there is nothing to commit, continue.
   Repeat until `git status` is clean.

3. **Fetch and check for updates.**
   ```bash
   git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
   CURRENT=$(git -C ~ rev-parse HEAD)
   LATEST=$(git -C ~ rev-parse FETCH_HEAD)
   echo "Current: $CURRENT, Latest: $LATEST"
   ```
   If `$CURRENT == $LATEST`, stop -- already up to date.

4. **Merge upstream.** At this point your local state should already be captured in a checkpoint commit, so you are integrating upstream into a clean local history instead of mixing file cleanup, local edits, and upstream changes in one step.
   ```bash
   git -C ~ merge FETCH_HEAD --no-edit
   ```
   If clean, skip to step 6.

5. **Resolve conflicts** using these rules:

   - Treat conflicts as integration work, not a choice between `ours` and `theirs`.
   - Default goal: preserve both functionalities and both intent sets in the merged result.
   - If the conflict is small, rewrite the merged file so both changes coexist directly.
   - If the conflict is structural, decouple the implementations:
     - extract helpers
     - split responsibilities
     - keep both call paths or behaviors
     - rename or reorganize logic to avoid collisions
   - **Vestad-managed paths** (`core/`, `pyproject.toml`, `uv.lock`) are not automatic `--theirs` files. If local behavior matters, carry it forward into the merged version.
   - Only take one side wholesale when the other side is clearly obsolete, redundant, generated, or a strict subset.
   - Do not stop at "conflict markers removed". Re-read the merged file and verify both sides' behavior still exists.

   After all conflicts are resolved: `git commit --no-edit`

6. **Verify.** `git status` should be clean, branch should be `$AGENT_NAME`, and the merged code should still preserve both sides' functionality. The history should read cleanly as: local checkpoint first, then upstream merge.

## Branch model

Your branch (named `$AGENT_NAME`) starts from the upstream ref you were deployed on. All local work is committed here. Before syncing, checkpoint your current local state so the history stays clean. Then merge upstream while preserving your customizations.

```
v0.1.132 (upstream ref)
  * local commits
  * merge upstream
  * more local commits
  * merge upstream
```

View local customizations vs upstream: `git diff FETCH_HEAD..$AGENT_NAME -- agent/` (after a fetch)
