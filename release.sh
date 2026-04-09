#!/usr/bin/env bash
set -euo pipefail

BUMP="${1:-patch}"

case "$BUMP" in
  patch|minor|major) ;;
  *) echo "Usage: ./release.sh [patch|minor|major]"; exit 1 ;;
esac

echo "Triggering $BUMP release..."
gh workflow run release.yml -f bump="$BUMP" || { echo "Failed to trigger workflow"; exit 1; }
echo "Release workflow started. Watch progress: gh run watch"
