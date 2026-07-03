#!/usr/bin/env bash
# Read-only: where this box stands vs its version's snapshot and the branch tip.
set -euo pipefail
cd ~
REF="${VESTA_WORKSPACE_REF:?VESTA_WORKSPACE_REF is unset}"
VERSION="$(grep '^version = ' agent/core/pyproject.toml | cut -d'"' -f2)"
TAG="agent-v$VERSION"
git fetch origin
echo "== running core: v$VERSION (snapshot $TAG)"
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  echo "== my changes on top of $TAG:"
  git log --oneline "$TAG..HEAD" || true
else
  echo "== snapshot $TAG not found on $REF"
fi
echo "== branch tip:"
git log --oneline -1 "refs/remotes/origin/$REF" 2>/dev/null || echo "(not fetched)"
