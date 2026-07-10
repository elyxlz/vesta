#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./release.sh [patch|minor|major] "<message>"

The message is required: user-facing "What's new" copy shown in the app and on
the changelog. Style:

  * Two or three short sentences in plain user language.
  * Name the headline features with a little texture; drop minor items.
  * Describe only what actually changed: a fix or backend improvement reads as
    "more reliable" or "now works with X", never as a brand-new capability.
  * Refer to the agent as Vesta or they/them, never it. No dashes as separators.
  * Internal-only release: an honest one-liner like "Small fixes under the hood."

Examples:
  ./release.sh "Vesta can now shop online, and hand you their browser when a site needs your login."
  ./release.sh minor "Any email account now works: full IMAP support with instant new-mail push."
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
