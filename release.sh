#!/usr/bin/env bash
set -euo pipefail

VERSION=$(grep '^version = ' agent/pyproject.toml | cut -d'"' -f2)
TAG="v${VERSION}"

if gh release view "$TAG" &>/dev/null; then
  echo "Release ${TAG} already exists"
  exit 1
fi

echo "Releasing ${TAG}..."
gh release create "$TAG" --title "$TAG" --generate-notes
