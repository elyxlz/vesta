#!/usr/bin/env bash
# One owner for the upgrade sync: put $HOME on the snapshot matching the core it now runs,
# with local work rebased on top. Mechanical steps only - a conflict is the agent's call.
# Exit: 0 synced (or already synced); 3 no snapshot tag for the running version;
# 5 the rebase stopped and needs conflicts resolved by hand.
set -euo pipefail
cd ~

SCRIPTS=~/agent/core/skills/upstream-sync/scripts
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"

bash "$SCRIPTS/fetch-upstream.sh"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || {
  echo "snapshot $TAG not in the upstream repo - is vestad on a different version?" >&2
  exit 3
}

# The cone is computed from HEAD, so recompute it whenever HEAD may have moved. It also pins
# the engine mount out of the worktree, which the rebase below depends on.
bash "$SCRIPTS/set-cone.sh"

# The authoritative question, and the one the boot turn re-fires on.
if git merge-base --is-ancestor "$TAG" HEAD; then
  echo "already synced: $TAG is in HEAD's history"
  exit 0
fi

# Checkpoint local work before rebasing, but exclude agent/core: on a managed box it is a read-only
# mount outside the sparse cone, so a bare "git add -A" errors on its out-of-cone (or ignored) paths
# and set -e would abort here, silently, before the rebase. "|| true" swallows the harmless notice git
# still prints for the excluded dir; a real staging failure is caught by the rebase's dirty-tree guard.
if [ -n "$(git status --porcelain -- . ':(exclude)agent/core')" ]; then
  git add -A -- . ':(exclude)agent/core' || true
  git diff --cached --quiet || git commit -q -m checkpoint
fi

# A managed box's engine is a read-only mount already running $TAG, so replaying a commit
# that touches agent/core would fail to unlink it, and the mount owns that content anyway.
if [ ! -w agent/core ]; then
  BASE="$(git describe --tags --match 'agent-v*' --abbrev=0 HEAD)"
  if [ -n "$(git log --oneline "$BASE..HEAD" -- agent/core)" ]; then
    git reset -q --soft "$BASE"
    git reset -q "$BASE" -- agent/core   # index-only: engine back to stock, mount untouched
    git diff --cached --quiet || git commit -q -m "my customizations"
  fi
fi

if ! git rebase "$TAG"; then
  echo "rebase stopped: resolve each conflict keeping BOTH sides, git add them, git rebase --continue, then re-run me" >&2
  exit 5
fi
bash "$SCRIPTS/set-cone.sh"   # HEAD moved
echo "synced onto $TAG"
