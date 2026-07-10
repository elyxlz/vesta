#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./release.sh [patch|minor|major] "<message>"

The message is required: user-facing marketing copy for the changelog
("What's new"), shown to users in the app and on the changelog.

Examples:
  ./release.sh "Faster startup and smoother chat scrolling."
  ./release.sh minor "Vesta can now manage your calendar."
EOF
  exit 1
}

BUMP="patch"
case "${1:-}" in
  patch|minor|major) BUMP="$1"; MESSAGE="${2:-}" ;;
  *) MESSAGE="${1:-}" ;;
esac

[ -n "$MESSAGE" ] || usage

echo "Triggering Release workflow (bump=${BUMP})..."
gh workflow run release.yml -f bump="$BUMP" -f message="$MESSAGE"

sleep 3
RUN_ID=$(gh run list --workflow=release.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "Watching run ${RUN_ID}..."
gh run watch "$RUN_ID" --exit-status

cat <<'EOF'

This ships a BETA (prerelease). Only opted-in beta clients receive it; stable users
are unaffected. Once it has soaked and you are happy, promote it to everyone with:

  ./promote.sh vX.Y.Z

If the beta turns out broken, pull it with:

  ./unrelease.sh vX.Y.Z

EOF
