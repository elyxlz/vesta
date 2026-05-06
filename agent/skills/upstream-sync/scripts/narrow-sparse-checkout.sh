#!/usr/bin/env bash
# Narrow ~/.git/info/sparse-checkout so agent/skills/*/ is opt-in: only currently-installed
# skill directories stay in the worktree. One-shot migration; idempotent on re-run.
#
# Snapshots a commit on the current branch before mutating the worktree, so a crash mid-reapply
# leaves the pre-narrow tree reachable from HEAD instead of silently wiped.
#
# Runs in the agent container; assumes $HOME is the repo root (the same assumption the inline
# bash in SKILL.md used).

set -euo pipefail

REPO="${HOME}"
SPARSE_FILE="${REPO}/.git/info/sparse-checkout"
GUARD='!/agent/skills/*/'

if grep -qFx "$GUARD" "$SPARSE_FILE" 2>/dev/null; then
  echo "sparse-checkout already narrow; nothing to do"
  exit 0
fi

# Pre-op snapshot: pin the soon-to-be-rewritten worktree state into HEAD before reapply.
git -C "$REPO" add agent/ --ignore-errors >/dev/null 2>&1 || true
if git -C "$REPO" diff --cached --quiet; then
  git -C "$REPO" commit --allow-empty -m "chore: pre-op snapshot before sparse-checkout narrow" >/dev/null
else
  git -C "$REPO" commit -m "chore: pre-op snapshot before sparse-checkout narrow" >/dev/null
fi

INSTALLED="$(find "$REPO/agent/skills" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -u)"

{
  printf '%s\n' '/agent/' '!/agent/core/' '!/agent/pyproject.toml' '!/agent/uv.lock' '!/agent/skills/*/' '/.gitignore'
  for s in $INSTALLED; do printf '/agent/skills/%s/\n' "$s"; done
} > "$SPARSE_FILE"

git -C "$REPO" sparse-checkout reapply
echo "sparse-checkout narrowed; installed: $(echo "$INSTALLED" | tr '\n' ' ')"
