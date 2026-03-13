#!/usr/bin/env bash
set -euo pipefail

BRANCH=$(git branch --show-current)
if [ "$BRANCH" != "master" ]; then
  echo "Must be on master branch (currently on $BRANCH)"
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "Working tree is dirty — commit or stash changes first"
  exit 1
fi

git pull --ff-only origin master

./bump.sh "${1:-patch}"

VERSION=$(grep '^version = ' agent/pyproject.toml | cut -d'"' -f2)
TAG="v${VERSION}"

if gh release view "$TAG" &>/dev/null; then
  echo "Release ${TAG} already exists"
  exit 1
fi

git add -A
git commit -m "Bump version to ${VERSION}"
git tag "$TAG"
git push origin master "$TAG"

echo "Releasing ${TAG}..."
gh release create "$TAG" --title "$TAG" --generate-notes
