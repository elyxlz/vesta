#!/usr/bin/env bash
# The App Store half of a promotion. Nothing is built here: the release pipeline
# delivered the iOS build to TestFlight, and this sends that build to App Store review.
#   gate    before the promotion: passes when the app in the store satisfies the
#           release's minimum client version. Otherwise it holds the promotion until
#           Apple has approved this version, then releases it.
#   submit  after the promotion: sends the build to review, to go public on approval.
set -euo pipefail

usage() {
  cat >&2 <<'EOF_USAGE'
Usage: submit-app-store.sh gate|submit vX.Y.Z

Requires fastlane and gh on PATH, plus an App Store Connect API key with the App
Manager role in APP_STORE_CONNECT_API_KEY_KEY_ID, APP_STORE_CONNECT_API_KEY_ISSUER_ID,
and APP_STORE_CONNECT_API_KEY_KEY (the .p8 content) or _KEY_FILEPATH.
EOF_USAGE
  exit 1
}

PHASE="${1:-}"
TAG="${2:-}"
case "$PHASE" in
  gate | submit) ;;
  *) usage ;;
esac
case "$TAG" in
  v*) ;;
  *) usage ;;
esac

script_dir=$(cd "$(dirname "$0")" && pwd)
cd "$script_dir/.."

body=$(gh release view "$TAG" --json body --jq .body | tr -d '\r')

# A release made with MOBILE_DELIVERY=skip has no build on TestFlight.
MOBILE_BUILD=0
case "$body" in
  *'<!-- mobile-delivery: testflight -->'*) MOBILE_BUILD=1 ;;
esac
if [ "$PHASE" = submit ] && [ "$MOBILE_BUILD" = 0 ]; then
  echo "$TAG shipped no mobile build, nothing to submit" >&2
  exit 0
fi

RELEASE_NOTES=$(printf '%s\n' "$body" | sed -n '/<!-- whats-new -->/,/<!-- \/whats-new -->/{//!p;}')
[ -n "$RELEASE_NOTES" ] || { echo "$TAG has no whats-new block in its release body" >&2; exit 1; }

MIN_CLIENT_VERSION=$(gh api "repos/{owner}/{repo}/contents/vestad/src/sync/mod.rs?ref=$TAG" \
  -H "Accept: application/vnd.github.raw" \
  | sed -n 's/.*MIN_SUPPORTED_CLIENT_VERSION: &str = "\([^"]*\)".*/\1/p')
[ -n "$MIN_CLIENT_VERSION" ] || { echo "could not read MIN_SUPPORTED_CLIENT_VERSION at $TAG" >&2; exit 1; }

export APP_VERSION="${TAG#v}" RELEASE_NOTES MIN_CLIENT_VERSION MOBILE_BUILD
fastlane "${PHASE}_app_store" >&2
