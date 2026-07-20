#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./release.sh [patch|minor|major] "<message>"

Set MOBILE_DELIVERY=testflight (the default) or MOBILE_DELIVERY=skip to control
whether this prerelease is delivered to internal TestFlight testers.

The message is required: user-facing "What's new" copy shown in the app and on
the changelog. Style:

  * Two to four short sentences in plain user language, one flowing paragraph;
    no markdown or bullets (both surfaces render it as plain text).
  * The first sentence carries the headline change; the website shows it alone
    as the announcement pill, so it must stand on its own.
  * Name each user-visible change with a little texture; sweep small fixes into
    one closing sentence ("Plus more reliable updates and sharper email search.").
  * Describe only what actually changed: a fix or backend improvement reads as
    "more reliable" or "now works with X", never as a brand-new capability.
  * Refer to the agent as Vesta or they/them, never it. No dashes as separators.
  * Internal-only release: an honest one-liner like "Small fixes under the hood."

Examples:
  ./release.sh "Vesta can now shop online, and hand you their browser when a site needs your login. Plus steadier updates on slow connections."
  ./release.sh minor "Any email account now works: full IMAP support with instant new-mail push. Vesta also answers faster when you interrupt them mid-task."
EOF
  exit 1
}

BUMP="patch"
case "${1:-}" in
  patch|minor|major) BUMP="$1"; MESSAGE="${2:-}" ;;
  *) MESSAGE="${1:-}" ;;
esac

[ -n "$MESSAGE" ] || usage

MOBILE_DELIVERY="${MOBILE_DELIVERY:-testflight}"
case "$MOBILE_DELIVERY" in
  testflight|skip) ;;
  *) echo "MOBILE_DELIVERY must be testflight or skip"; exit 1 ;;
esac

# Client-compatibility guard: the gateway we ship must accept the client bundled with it. The
# smallest version any bump can produce is a patch bump of the current version; if
# MIN_SUPPORTED_CLIENT_VERSION sits at or below that, it sits below every possible release, so a
# value above it would ship a gateway that locks out every client (see the Client compatibility
# contract in CLAUDE.md). Parse both from the vestad source and refuse to release on violation.
MIN_SUPPORTED=$(sed -n 's/.*MIN_SUPPORTED_CLIENT_VERSION: &str = "\([^"]*\)".*/\1/p' vestad/src/sync/mod.rs)
CURRENT_VERSION=$(sed -n 's/^version = "\([^"]*\)".*/\1/p' vestad/Cargo.toml | head -1)
IFS='.' read -r VMAJ VMIN VPATCH <<<"$CURRENT_VERSION"
SMALLEST_NEXT="${VMAJ}.${VMIN}.$((VPATCH + 1))"
if [ "$(printf '%s\n%s\n' "$MIN_SUPPORTED" "$SMALLEST_NEXT" | sort -V | tail -n1)" != "$SMALLEST_NEXT" ]; then
  echo "MIN_SUPPORTED_CLIENT_VERSION (${MIN_SUPPORTED}) is above the next release (${SMALLEST_NEXT});" >&2
  echo "releasing would lock out every client. Fix it in vestad/src/sync/mod.rs." >&2
  exit 1
fi

echo "Triggering Release workflow (bump=${BUMP}, mobile=${MOBILE_DELIVERY})..."
gh workflow run release.yml -f bump="$BUMP" -f message="$MESSAGE" -f mobile_delivery="$MOBILE_DELIVERY"

sleep 3
RUN_ID=$(gh run list --workflow=release.yml --limit=1 --json databaseId --jq '.[0].databaseId')
echo "Watching run ${RUN_ID}..."
gh run watch "$RUN_ID" --exit-status

# The prerelease is published; release-pipeline.yml now fires on that event to
# build and deliver. It reverts its own runtime failures, but a run rejected at
# validation never schedules jobs, so that in-pipeline revert can't fire and the
# broken tag would linger. Watch the pipeline through startup and pull the beta
# here if it never launches.
TAG=$(gh release list --limit 1 --json tagName --jq '.[0].tagName')
echo
echo "Prerelease ${TAG} created. Confirming the delivery pipeline launches..."

PIPELINE_ID=""
for _ in $(seq 1 30); do
  PIPELINE_ID=$(gh run list --workflow=release-pipeline.yml --event=release --limit 10 \
    --json databaseId,displayTitle \
    --jq "map(select(.displayTitle == \"${TAG}\")) | .[0].databaseId // empty")
  [ -n "$PIPELINE_ID" ] && break
  sleep 4
done

if [ -z "$PIPELINE_ID" ]; then
  echo "Warning: no release-pipeline run found for ${TAG} yet; watch it in Actions."
else
  while true; do
    read -r STATUS CONCLUSION <<<"$(gh run view "$PIPELINE_ID" --json status,conclusion --jq '"\(.status) \(.conclusion // "")"')"
    if [ "$STATUS" = "completed" ] && [ "$CONCLUSION" = "startup_failure" ]; then
      echo "The release pipeline for ${TAG} failed at startup, so its own cleanup never ran."
      echo "Pulling the broken beta..."
      gh workflow run unrelease.yml -f tag="$TAG"
      echo "Fix the workflow, then re-run ./release.sh."
      exit 1
    fi
    [ "$STATUS" = "queued" ] || break
    sleep 5
  done
  echo "Pipeline launched for ${TAG}; it owns delivery and cleanup from here."
fi

cat <<'EOF'

This ships a BETA (prerelease). Only opted-in beta clients receive it; stable users
are unaffected. Once it has soaked and you are happy, promote it to everyone with:

  ./promote.sh vX.Y.Z

If the beta turns out broken, pull it with:

  ./unrelease.sh vX.Y.Z

EOF
