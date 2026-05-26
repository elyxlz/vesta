---
name: upstream-sync
description: Sync local agent code with upstream vesta: updates, merges, conflicts.
---

# Upstream Sync

Pull updates in. To push contributions out, see [upstream-pr](../upstream-pr/SKILL.md).

Bring your local workspace into order, checkpoint your current state on your branch, then merge upstream. Goal: a clean, easy-to-merge shape relative to `$VESTA_UPSTREAM_REF` (a release tag in prod, e.g. `v0.1.132`, or a branch in dev, e.g. `feat/agent-source-dir`).

## Ownership

`~` is the repo root. Sparse checkout limits the worktree to `agent/` (minus bind-mounted paths and uninstalled skills) and root `.gitignore`. Skill directories under `agent/skills/*/` are opt-in: only installed skills are on disk and in `git status`. `agent/skills/index.json` is always visible: it's the registry of available skills, regardless of what's installed. Repo-root `.claude/` stays local and untracked. Bulky/local-only stuff goes in `~/agent/.gitignore`.

You own `agent/skills/`, `agent/prompts/`, `agent/MEMORY.md`, `agent/.gitignore`, and `.claude/`. Commits focus on `agent/`.

`agent/core/`, `agent/pyproject.toml`, `agent/uv.lock` are bind-mounted read-only by vestad; merge conflicts there still need integration work if both sides carry meaningful behavior.

## Worktree safety

Any git command that mutates the worktree (`sparse-checkout reapply`/`init`, `checkout -- <path>`, `reset --hard`, `clean -df`, `merge`, `rebase`, `read-tree`) must be preceded by a snapshot commit on your branch. If `git status` is dirty, run `git -C ~ add agent/ --ignore-errors && git -C ~ commit -m "pre-op: <what you're about to do>"`. If clean, run `git -C ~ commit --allow-empty -m "pre-op: <what>"`. Reflog is per-clone and dies with the container, so a real commit on your branch is the only durable safety net before destructive ops. Wrapper scripts under `scripts/` already enforce this internally; prefer them over raw git for the migrations below.

## Sync steps

1. **Normalize.** If the workspace is not in the expected shape, follow [SETUP.md](SETUP.md) first.

2. **Checkpoint local work.** The merge fails with uncommitted changes; the checkpoint also gives you a clean base.
   ```bash
   cd ~
   git add agent/ --ignore-errors
   # Drop accidental non-agent deletions so upstream's tree wins on merge.
   git diff --cached --name-only --diff-filter=D | grep -v '^agent/' | xargs -r git reset HEAD -- 2>/dev/null || true
   git status
   ```
   `~/agent/.gitignore` should already exclude bulky files. If `git status` shows any, add the pattern and re-stage. Once clean:
   ```bash
   git -C ~ commit -m "chore: checkpoint local state before $VESTA_UPSTREAM_REF upstream sync"
   ```
   Skip the commit if nothing's staged.

   **Bind-mount drift.** If `agent/pyproject.toml` or `agent/uv.lock` show as modified after step 2 (the image rebuild bumped them and the `skip-worktree` bit got cleared), the merge will abort with "Your local changes ... would be overwritten." Commit them as a baseline first; they're outside the sparse pattern so `--sparse` is required:
   ```bash
   git -C ~ update-index --no-skip-worktree agent/pyproject.toml agent/uv.lock 2>/dev/null || true
   git -C ~ add --sparse agent/pyproject.toml agent/uv.lock
   git -C ~ commit -m "chore: sync bind-mount state baseline" 2>/dev/null || true
   ```

3. **Narrow sparse pattern (one-shot migration).** Scope `agent/skills/*/` to only currently-installed skills so future merges don't pull in newly-added upstream skills. Run after step 2 so a recoverable HEAD exists before the worktree is rewritten:
   ```bash
   ~/agent/skills/upstream-sync/scripts/narrow-sparse-checkout.sh
   ```
   Idempotent: exits 0 with no changes if already narrow. The script snapshots an `--allow-empty` commit on your branch before calling `sparse-checkout reapply`, so a crash mid-reapply leaves the pre-narrow tree reachable from HEAD.

4. **Fetch and check.**
   ```bash
   git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
   [ "$(git -C ~ rev-parse HEAD)" = "$(git -C ~ rev-parse FETCH_HEAD)" ] && echo "up to date" || echo "updates available"
   ```
   If up to date, stop.

5. **Merge.**
   ```bash
   git -C ~ merge FETCH_HEAD --no-edit
   ```
   If clean, skip to step 7.

6. **Resolve conflicts.**
   - Treat conflicts as integration work, not `ours` vs `theirs`. Default goal: preserve both behaviors.
   - Small: rewrite the merged file so both changes coexist.
   - Structural: extract helpers, split responsibilities, rename to avoid collisions.
   - **Vestad-managed paths** (`core/`, `pyproject.toml`, `uv.lock`) are not automatic `--theirs`. If local behavior matters, carry it forward.
   - Take one side wholesale only when the other is obsolete, redundant, generated, or a strict subset.
   - Don't stop at "markers removed". Re-read the file and verify both sides' behavior survives.

   Then: `git -C ~ commit --no-edit`

7. **Reconcile generated artifacts.** Two things upstream cannot merge cleanly that need a deterministic post-merge fix:

   - `agent/skills/index.json` is generated from disk. A textual merge of two arrays sometimes produces invalid or stale JSON, and any new skill directory pulled in from upstream needs an entry. Regenerate from the merged tree:
     ```bash
     cd ~/agent && uv run python skills/generate-index.py
     ```
   - `git merge` re-stats the working tree, which clears the `skip-worktree` bit on some bind-mounted paths. Re-apply **only when those paths are actually bind-mounted** (vestad-managed containers); on unmanaged containers they are real tracked files and must remain editable / committable:
     ```bash
     if mount | grep -q '/root/agent/core '; then
       git -C ~ ls-files agent/core agent/pyproject.toml agent/uv.lock | xargs -r git -C ~ update-index --skip-worktree
     fi
     ```

   If the regen changed `index.json`, commit it on top of the merge:
   ```bash
   git -C ~ add agent/skills/index.json && git -C ~ commit -m "chore: refresh skills/index.json post-sync"
   ```

8. **Verify.** `git status` clean, branch is `$AGENT_NAME`, both sides' functionality preserved. History reads: local checkpoint, then upstream merge, then (optionally) the index refresh.

## Branch model

Your branch (`$AGENT_NAME`) starts from `$VESTA_UPSTREAM_REF`. All local work commits here. Sync = checkpoint, then merge upstream on top.

```
v0.1.132 (upstream ref)
  * local commits
  * merge upstream
  * more local commits
  * merge upstream
```

Diff vs upstream: `git -C ~ fetch origin "$VESTA_UPSTREAM_REF" && git -C ~ diff FETCH_HEAD -- agent/`. Default to working-tree-vs-upstream (one ref, no `..HEAD`) so uncommitted edits show up. Use `FETCH_HEAD...HEAD` only for the strict committed-PR view. (`origin/master` is only correct for outbound `upstream-pr` worktrees.)

## Troubleshooting

**Tree looks stripped** (existing agents from before sparse-checkout was fixed):
```bash
git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
ROOT_ENTRIES=$(git -C ~ ls-tree --name-only HEAD 2>/dev/null | wc -l)
MISSING=$(git -C ~ diff FETCH_HEAD HEAD --name-status 2>/dev/null | grep -c '^D' || echo 0)
if [ "$ROOT_ENTRIES" -lt 5 ] || [ "$MISSING" -gt 10 ]; then
  git -C ~ ls-tree -r FETCH_HEAD | while IFS=$'\t' read mode_type_hash path; do
    [ -z "$(git -C ~ ls-tree HEAD -- "$path" 2>/dev/null)" ] && {
      mode=$(echo "$mode_type_hash" | awk '{print $1}')
      hash=$(echo "$mode_type_hash" | awk '{print $3}')
      git -C ~ update-index --add --cacheinfo "$mode,$hash,$path"
    }
  done
  git -C ~ commit -m "fix: restore full upstream tree (self-heal)" --allow-empty
fi
```

**Root `.gitignore` shows as `D` after a past merge** (pre-fix bug, harmless to fix):
```bash
git -C ~ checkout origin/$VESTA_UPSTREAM_REF -- .gitignore
git -C ~ commit -m "fix: restore root .gitignore"
```
