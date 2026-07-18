#!/usr/bin/env bash
set -euo pipefail

TAG="${1:-}"
if [ -z "$TAG" ]; then
  echo "usage: $0 <image-tag>" >&2
  exit 2
fi
: "${GH_TOKEN:?GH_TOKEN must authenticate gh package operations}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be owner/repository}"

OWNER="${GITHUB_REPOSITORY%%/*}"
PACKAGE_NAME="${GITHUB_REPOSITORY#*/}"
set +e
OWNER_TYPE=$(gh api "users/${OWNER}" --jq .type)
owner_status=$?
if [ "$owner_status" -eq 0 ] && [ "$OWNER_TYPE" = "Organization" ]; then
  PACKAGE_SCOPE="orgs/${OWNER}"
else
  PACKAGE_SCOPE="users/${OWNER}"
fi
VERSION_ID=$(gh api "${PACKAGE_SCOPE}/packages/container/${PACKAGE_NAME}/versions" \
  --paginate | \
  jq -r --arg tag "$TAG" '.[] | select(.metadata.container.tags | index($tag)) | .id' | \
  awk 'NF && !found { value=$0; found=1 } END { if (found) print value }')
lookup_status=$?
set -e

if [ "$lookup_status" -ne 0 ]; then
  echo "::warning::failed to inspect GHCR versions; continuing release cleanup"
  exit 0
fi

if [ -z "$VERSION_ID" ]; then
  echo "::warning::no GHCR image tagged ${TAG} was found; skipping image cleanup"
  exit 0
fi

if gh api --method DELETE "users/${OWNER}/packages/container/${PACKAGE_NAME}/versions/${VERSION_ID}"; then
  echo "Deleted ghcr.io/${GITHUB_REPOSITORY}:${TAG} (package version ${VERSION_ID})"
else
  echo "::warning::failed to delete GHCR package version ${VERSION_ID}; continuing cleanup"
fi

# Image deletion is best-effort. A stale, unreferenced version tag is safer
# than preventing the GitHub release and git tag from being removed.
exit 0
