---
name: upstream-sync
description: Sync local agent code with upstream vesta: updates, merges, conflicts.
---

# Upstream Sync

Pull updates in. To push contributions out, see [upstream-pr](../upstream-pr/SKILL.md).

Bring your local workspace into order, checkpoint your current state on your branch, then merge upstream. Goal: a clean, easy-to-merge shape relative to `$VESTA_UPSTREAM_REF` (a release tag in prod, e.g. `v0.1.132`, or a branch in dev, e.g. `feat/agent-source-dir`).

## Ownership

`~` is the repo root. Sparse checkout limits the worktree to `agent/` (minus bind-mounted paths and uninstalled skills) and root `.gitignore`. Skill directories under `agent/skills/*/` are opt-in: only installed skills are on disk and in `git status`. `agent/skills/index.json` is always visible — it's the registry of available skills, regardless of what's installed. Repo-root `.claude/` stays local and untracked. Bulky/local-only stuff goes in `~/agent/.gitignore`.

You own `agent/skills/`, `agent/prompts/`, `agent/MEMORY.md`, `agent/.gitignore`, and `.claude/`. Commits focus on `agent/`.

`agent/core/`, `agent/pyproject.toml`, `agent/uv.lock` are bind-mounted read-only by vestad; merge conflicts there still need integration work if both sides carry meaningful behavior.

## Sync steps

1. **Normalize.** If the workspace is not in the expected shape, follow [SETUP.md](SETUP.md) first. Then narrow the sparse pattern to installed-only if it isn't already:
   ```bash
   if ! grep -qx '!/agent/skills/\*/' ~/.git/info/sparse-checkout 2>/dev/null; then
     INSTALLED=$(find ~/agent/skills -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -u)
     {
       printf '%s\n' '/agent/' '!/agent/core/' '!/agent/pyproject.toml' '!/agent/uv.lock' '!/agent/skills/*/' '/.gitignore'
       for s in $INSTALLED; do printf '/agent/skills/%s/\n' "$s"; done
     } > ~/.git/info/sparse-checkout
     git -C ~ sparse-checkout reapply
   fi
   ```
   This is a one-shot migration: it rewrites the sparse pattern to scope `agent/skills/*/` to only currently-installed skills, so future merges don't pull in newly-added upstream skills. Idempotent — the `grep` guard skips re-runs.

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

3. **Fetch and check.**
   ```bash
   git -C ~ fetch origin "$VESTA_UPSTREAM_REF"
   [ "$(git -C ~ rev-parse HEAD)" = "$(git -C ~ rev-parse FETCH_HEAD)" ] && echo "up to date" || echo "updates available"
   ```
   If up to date, stop.

4. **Merge.**
   ```bash
   git -C ~ merge FETCH_HEAD --no-edit
   ```
   If clean, skip to step 6.

5. **Resolve conflicts.**
   - Treat conflicts as integration work, not `ours` vs `theirs`. Default goal: preserve both behaviors.
   - Small: rewrite the merged file so both changes coexist.
   - Structural: extract helpers, split responsibilities, rename to avoid collisions.
   - **Vestad-managed paths** (`core/`, `pyproject.toml`, `uv.lock`) are not automatic `--theirs`. If local behavior matters, carry it forward.
   - Take one side wholesale only when the other is obsolete, redundant, generated, or a strict subset.
   - Don't stop at "markers removed". Re-read the file and verify both sides' behavior survives.

   Then: `git -C ~ commit --no-edit`

6. **Verify.** `git status` clean, branch is `$AGENT_NAME`, both sides' functionality preserved. History reads: local checkpoint, then upstream merge.

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
