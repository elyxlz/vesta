#!/usr/bin/env bash
# Read-only: where this box stands vs its version's snapshot and the workspace tip.
set -euo pipefail
cd ~
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"
bash ~/agent/core/skills/workspace-sync/scripts/fetch-workspace.sh
echo "== running core: v$VERSION (snapshot $TAG)"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "== my changes on top of $TAG:"
  git log --oneline "$TAG..HEAD" || true
else
  echo "== snapshot $TAG not in the workspace bundle"
fi
echo "== workspace tip:"
git log --oneline -1 "refs/remotes/origin/agent-workspace" 2>/dev/null || echo "(not fetched)"
