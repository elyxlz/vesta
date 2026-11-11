#!/usr/bin/env bash
# Send the iOS build that TestFlight already holds for one release to App Store
# review. Nothing is built here: the release pipeline delivered the build, and
# Apple releases it to the public once the review approves it.
set -euo pipefail

usage() {
  cat >&2 <<'EOF_USAGE'
Usage: submit-app-store.sh vX.Y.Z

Requires fastlane and gh on PATH, plus the App Store Connect API key in
APP_STORE_CONNECT_API_KEY_KEY_ID, APP_STORE_CONNECT_API_KEY_ISSUER_ID, and
APP_STORE_CONNECT_API_KEY_KEY (the .p8 content). The key needs the App Manager role.
EOF_USAGE
  exit 1
}

TAG="${1:-}"
case "$TAG" in
  v*) ;;
  *) usage ;;
esac

script_dir=$(cd "$(dirname "$0")" && pwd)
cd "$script_dir/.."

body=$(gh release view "$TAG" --json body --jq .body | tr -d '\r')

# A release made with MOBILE_DELIVERY=skip has no build on TestFlight.
case "$body" in
  *'<!-- mobile-delivery: testflight -->'*) ;;
  *) echo "$TAG shipped no mobile build, nothing to submit" >&2; exit 0 ;;
esac

notes=$(printf '%s\n' "$body" | sed -n '/<!-- whats-new -->/,/<!-- \/whats-new -->/{//!p;}')
[ -n "$notes" ] || { echo "$TAG has no whats-new block in its release body" >&2; exit 1; }

echo "Submitting ${TAG#v} to App Store review..." >&2
APP_VERSION="${TAG#v}" RELEASE_NOTES="$notes" fastlane submit_app_store >&2
