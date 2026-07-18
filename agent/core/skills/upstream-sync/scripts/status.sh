#!/usr/bin/env bash
# Read-only: where this box stands vs its version's snapshot and the upstream tip.
set -euo pipefail
cd ~
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"
bash ~/agent/core/skills/upstream-sync/scripts/fetch-upstream.sh
echo "== running core: v$VERSION (snapshot $TAG)"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  # `$TAG..HEAD` lists my commits either way, so only merge-base says whether the rebase landed.
  if git merge-base --is-ancestor "$TAG" HEAD; then
    echo "== synced: my changes on top of $TAG:"
  else
    echo "== NOT synced: $TAG is not in my history, run sync.sh. My commits:"
  fi
  git log --oneline "$TAG..HEAD" || true
else
  echo "== snapshot $TAG not in the upstream repo"
fi
echo "== upstream tip:"
git log --oneline -1 "refs/remotes/upstream/agent-upstream" 2>/dev/null || echo "(not fetched)"
