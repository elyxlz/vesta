#!/usr/bin/env bash
set -euo pipefail

# Promote a beta (prerelease) to stable for everyone. Run after ./release.sh has
# shipped a beta and it has soaked. Moves the agent image :latest tag, flips the
# GitHub release to latest, and advances production. No rebuild happens.

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
