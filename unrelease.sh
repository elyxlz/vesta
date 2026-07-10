#!/usr/bin/env bash
set -euo pipefail

# Pull a broken beta (prerelease). Deletes the GitHub release, its git tag, and the
# ghcr image tag; refuses to touch a promoted (stable) release. The version-bump
# commit on master stays, the version number is burned.

TAG="${1:-}"

case "$TAG" in
  v*) ;;
  *) echo "Usage: ./unrelease.sh vX.Y.Z"; exit 1 ;;
esac

echo "Triggering Unrelease workflow (tag=${TAG})..."
gh workflow run unrelease.yml -f tag="$TAG"

sleep 3
RUN_ID=$(gh run list --workflow=unrelease.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "Watching run ${RUN_ID}..."
gh run watch "$RUN_ID" --exit-status

cat <<'EOF'

Pulled. Boxes already on this beta stay on it (updates are forward-only), so ship a
fixed release right after:

  ./release.sh "<message>"

EOF
