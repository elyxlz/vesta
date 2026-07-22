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

# The authoritative question, and the one the boot turn re-fires on.
if git merge-base --is-ancestor "$TAG" HEAD; then
  echo "already synced: $TAG is in HEAD's history"
  exit 0
fi

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git diff --cached --quiet || git commit -q -m checkpoint
fi

# The snapshot carries only skills + MEMORY.md (core is a gitignored read-only mount), so
# the rebase never replays a commit onto the engine mount.
if ! git rebase "$TAG"; then
  echo "rebase stopped: resolve each conflict keeping BOTH sides, git add them, git rebase --continue, then re-run me" >&2
  exit 5
fi
echo "synced onto $TAG"
