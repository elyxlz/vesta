#!/usr/bin/env bash
# One owner for the upgrade sync: put $HOME on the snapshot matching the core it now runs,
# with local work rebased on top. Mechanical steps only - a conflict is the agent's call and
# stops the script.
#
# On a managed box agent/core is vestad's read-only mount: the engine already runs the target
# version, so the rebase has nothing to do there and must not try. set-cone.sh pins those
# paths out of the worktree, and local commits carrying engine paths (a legacy in-cone box, a
# blanket `add -A --sparse`) are collapsed away first - replaying them would fail unlinking a
# read-only file, and the mount owns that content anyway (issue #1280).
#
# Exit: 0 synced (or already synced); 3 snapshot tag for the running version is missing;
# 5 the rebase stopped and needs conflicts resolved by hand.
set -euo pipefail
cd ~

VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"

bash ~/agent/core/skills/upstream-sync/scripts/fetch-upstream.sh
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || {
  echo "snapshot $TAG not in the upstream repo - is vestad on a different version?" >&2
  exit 3
}

# The authoritative question, and the one the boot turn re-fires on.
if git merge-base --is-ancestor "$TAG" HEAD; then
  echo "already synced: $TAG is in HEAD's history"
  exit 0
fi

# Cone first: on a managed box this is what makes the rebase's checkout of $TAG update the
# index alone instead of rewriting the engine mount.
bash ~/agent/core/skills/upstream-sync/scripts/set-cone.sh

if [ -n "$(git status --porcelain)" ]; then
  git add -A
  git commit -q -m checkpoint
fi

BASE="$(git describe --tags --match 'agent-v*' --abbrev=0 HEAD)"
if [ ! -w agent/core ] && [ -n "$(git log --oneline "$BASE..HEAD" -- agent/core)" ]; then
  git reset -q --soft "$BASE"
  git reset -q "$BASE" -- agent/core   # index-only: engine paths back to stock, mount untouched
  git diff --cached --quiet || git commit -q -m "my customizations"
fi

if ! git rebase "$TAG"; then
  echo "rebase stopped: resolve each conflict keeping BOTH sides, git add them, then git rebase --continue" >&2
  exit 5
fi
echo "synced onto $TAG"
