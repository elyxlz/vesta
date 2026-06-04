#!/usr/bin/env bash
set -euo pipefail

BUMP="${1:-patch}"

case "$BUMP" in
  patch|minor|major) ;;
  *) echo "Usage: ./release.sh [patch|minor|major]"; exit 1 ;;
esac

echo "Triggering Release workflow (bump=${BUMP})..."
gh workflow run release.yml -f bump="$BUMP"

sleep 3
RUN_ID=$(gh run list --workflow=release.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "Watching run ${RUN_ID}..."
gh run watch "$RUN_ID" --exit-status

cat <<'EOF'

This ships a BETA (prerelease). Only opted-in beta clients receive it; stable users
are unaffected. Once it has soaked and you are happy, promote it to everyone with:

  ./promote.sh vX.Y.Z

EOF
