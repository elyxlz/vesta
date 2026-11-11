#!/usr/bin/env bash
set -euo pipefail

# Promote a soaked beta (prerelease) to stable for everyone, with no rebuild: moves
# the image :latest tag, flips the GitHub release to latest (older betas cascade to
# stable too), advances production, and sends the iOS build that TestFlight holds
# to App Store review. A release that needs an app newer than the one in the App
# Store takes two runs: the first sends the app to review and fails without
# promoting, and a run after Apple's approval releases the app and promotes.

TAG="${1:-}"

case "$TAG" in
  v*) ;;
  *) echo "Usage: ./promote.sh vX.Y.Z"; exit 1 ;;
esac

echo "Triggering Promote workflow (tag=${TAG})..."
gh workflow run promote.yml -f tag="$TAG"

sleep 3
RUN_ID=$(gh run list --workflow=promote.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "Watching run ${RUN_ID}..."
gh run watch "$RUN_ID" --exit-status
